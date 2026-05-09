#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/functional.h>
#include <vector>
#include <cmath>
#include <limits>
#include <queue>
#include <algorithm>
#include <thread>
#include <atomic>
#include <numeric>
namespace py = pybind11;

// 儲存斷線後的直徑資訊
struct DiameterInfo {
    int dist = 0;
    int nodeA = -1;
    int nodeB = -1;
};

// 擴展結果結構，包含詳細統計
struct SearchResult {
    std::vector<int> best_assignment;
    int valid_count = 0;
    int best_count = 0;
    double m1 = 0, m2 = 0, m3 = 0, final_score = 0;

    // --- 新增詳細統計欄位 ---
    std::vector<int> group_edge_counts; // 每一組有多少邊
    std::vector<std::vector<int>> node_group_distribution; // 每個 node 在各組的邊數 [node_idx][group_idx]
    std::vector<DiameterInfo> group_removal_details; // 斷開每一組後的直徑詳情
};

struct ThreadLocalBounds {
    double mi1 = std::numeric_limits<double>::max(), ma1 = std::numeric_limits<double>::lowest();
    double mi2 = std::numeric_limits<double>::max(), ma2 = std::numeric_limits<double>::lowest();
    double mi3 = std::numeric_limits<double>::max(), ma3 = std::numeric_limits<double>::lowest();
    SearchResult result;
};

// 修改 BFS，回傳距離最遠的節點 ID
struct BFSResult {
    int dist;
    int furthest_node;
    int visited_count;
};

BFSResult get_furthest_info(int num_nodes, const std::vector<std::vector<int>>& adj, int start_node) {
    std::vector<int> dists(num_nodes, -1);
    std::queue<int> q;
    q.push(start_node);
    dists[start_node] = 0;
    int visited = 1;
    int max_d = 0;
    int furthest = start_node;

    while(!q.empty()) {
        int u = q.front(); q.pop();
        if (dists[u] > max_d) {
            max_d = dists[u];
            furthest = u;
        }
        for(int v : adj[u]) {
            if(dists[v] == -1) {
                dists[v] = dists[u] + 1;
                visited++;
                q.push(v);
            }
        }
    }
    return {max_d, furthest, visited};
}

inline double norm(double v, double mi, double ma) {
    return (ma != mi) ? (v - mi) / (ma - mi) : 0.0;
}

void idx_to_assignment(unsigned long long idx, int k, int E, std::vector<int>& assignment) {
    assignment[0] = 0;
    for (int i = E - 1; i > 0; --i) {
        assignment[i] = idx % k;
        idx /= k;
    }
}

py::dict search_best_assignment(
    int k, int num_nodes, 
    std::vector<std::pair<int, int>> edges, 
    std::vector<double> weights,
    std::function<bool(unsigned long long, unsigned long long)> progress_callback
) {
    int E = edges.size();
    if (E == 0 || num_nodes == 0) return py::dict();

    unsigned long long total_combinations = std::pow(k, std::max(0, E - 1));
    unsigned int num_threads = std::thread::hardware_concurrency();
    if (num_threads == 0) num_threads = 4;

    unsigned long long chunk_size = total_combinations / num_threads;
    std::atomic<unsigned long long> global_count(0);
    std::atomic<bool> global_stop_flag(false);
    std::vector<ThreadLocalBounds> thread_results(num_threads);
    std::vector<std::thread> threads;

    double W1 = weights[0], W2 = weights[1], W3 = weights[2];
    int target_mask = (1 << k) - 1;

    py::gil_scoped_release release;

    for (unsigned int t = 0; t < num_threads; ++t) {
        threads.emplace_back([&, t]() {
            unsigned long long start_idx = t * chunk_size;
            unsigned long long end_idx = (t == num_threads - 1) ? total_combinations : (t + 1) * chunk_size;
            
            std::vector<int> assignment(E, 0);
            idx_to_assignment(start_idx, k, E, assignment);
            std::vector<std::vector<int>> adj(num_nodes);
            
            ThreadLocalBounds& local = thread_results[t];
            unsigned long long local_loop_count = 0;

            for (unsigned long long idx = start_idx; idx < end_idx; ++idx) {
                if (global_stop_flag.load(std::memory_order_relaxed)) break;
                local_loop_count++;
                if (local_loop_count % 100000 == 0) global_count.fetch_add(100000, std::memory_order_relaxed);

                int mask = 0;
                for (int g : assignment) mask |= (1 << g);
                
                if (mask == target_mask) {
                    bool is_valid = true;
                    int global_max_dia = 0;
                    std::vector<DiameterInfo> current_diameters(k);

                    for (int g_remove = 0; g_remove < k; ++g_remove) {
                        for(int i = 0; i < num_nodes; ++i) adj[i].clear();
                        for (int i = 0; i < E; ++i) {
                            if (assignment[i] != g_remove) {
                                adj[edges[i].first].push_back(edges[i].second);
                                adj[edges[i].second].push_back(edges[i].first);
                            }
                        }

                        // 1. 檢查連通性
                        BFSResult check = get_furthest_info(num_nodes, adj, 0);
                        if (check.visited_count < num_nodes) { is_valid = false; break; }

                        // 2. 計算直徑
                        DiameterInfo dia;
                        for (int n = 0; n < num_nodes; ++n) {
                            BFSResult res = get_furthest_info(num_nodes, adj, n);
                            if (res.dist > dia.dist) {
                                dia.dist = res.dist;
                                dia.nodeA = n;
                                dia.nodeB = res.furthest_node;
                            }
                        }
                        current_diameters[g_remove] = dia;
                        global_max_dia = std::max(global_max_dia, dia.dist);
                    }

                    if (is_valid) {
                        local.result.valid_count++;
                        
                        // 計算 M1
                        std::vector<int> group_counts(k, 0);
                        for (int g : assignment) group_counts[g]++;
                        double m1 = 0; double exp = (double)E / k;
                        for (int c : group_counts) m1 += (c - exp) * (c - exp);

                        // 計算 M2
                        double m2 = 0;
                        std::vector<std::vector<int>> node_dist(num_nodes, std::vector<int>(k, 0));
                        for (int n = 0; n < num_nodes; ++n) {
                            for (int i = 0; i < E; ++i) {
                                if (edges[i].first == n || edges[i].second == n) node_dist[n][assignment[i]]++;
                            }
                            double avg = (double)std::accumulate(node_dist[n].begin(), node_dist[n].end(), 0) / k;
                            for (int c : node_dist[n]) m2 += (c - avg) * (c - avg);
                        }

                        double m3 = global_max_dia;

                        local.mi1 = std::min(local.mi1, m1); local.ma1 = std::max(local.ma1, m1);
                        local.mi2 = std::min(local.mi2, m2); local.ma2 = std::max(local.ma2, m2);
                        local.mi3 = std::min(local.mi3, m3); local.ma3 = std::max(local.ma3, m3);

                        double curr_score = W1 * norm(local.result.m1, local.mi1, local.ma1) + 
                                            W2 * norm(local.result.m2, local.mi2, local.ma2) + 
                                            W3 * norm(local.result.m3, local.mi3, local.ma3);
                        double cand_score = W1 * norm(m1, local.mi1, local.ma1) + 
                                            W2 * norm(m2, local.mi2, local.ma2) + 
                                            W3 * norm(m3, local.mi3, local.ma3);

                        if (local.result.valid_count == 1 || cand_score < curr_score - 1e-9) {
                            local.result.best_assignment = assignment;
                            local.result.m1 = m1; local.result.m2 = m2; local.result.m3 = m3;
                            local.result.final_score = cand_score; local.result.best_count = 1;
                            local.result.group_edge_counts = group_counts;
                            local.result.node_group_distribution = node_dist;
                            local.result.group_removal_details = current_diameters;
                        } else if (std::abs(cand_score - curr_score) <= 1e-9) {
                            local.result.best_count++;
                        }
                    }
                }

                int i = E - 1;
                while (i > 0) {
                    assignment[i]++;
                    if (assignment[i] < k) break;
                    assignment[i] = 0;
                    i--;
                }
            }
            global_count.fetch_add(local_loop_count % 100000, std::memory_order_relaxed);
        });
    }

    while (true) {
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
        unsigned long long current = global_count.load(std::memory_order_relaxed);
        {
            py::gil_scoped_acquire acquire;
            if (progress_callback && !progress_callback(current, total_combinations)) global_stop_flag.store(true);
        }
        if (current >= total_combinations || global_stop_flag.load()) break;
    }

    for (auto& th : threads) if (th.joinable()) th.join();

    py::gil_scoped_acquire acquire;
    py::dict py_result;
    int total_valid = 0;
    double g_mi1 = std::numeric_limits<double>::max(), g_ma1 = std::numeric_limits<double>::lowest();
    double g_mi2 = std::numeric_limits<double>::max(), g_ma2 = std::numeric_limits<double>::lowest();
    double g_mi3 = std::numeric_limits<double>::max(), g_ma3 = std::numeric_limits<double>::lowest();

    for (const auto& l : thread_results) {
        total_valid += l.result.valid_count;
        if (l.result.valid_count > 0) {
            g_mi1 = std::min(g_mi1, l.mi1); g_ma1 = std::max(g_ma1, l.ma1);
            g_mi2 = std::min(g_mi2, l.mi2); g_ma2 = std::max(g_ma2, l.ma2);
            g_mi3 = std::min(g_mi3, l.mi3); g_ma3 = std::max(g_ma3, l.ma3);
        }
    }

    if (total_valid > 0) {
        SearchResult final_best; bool first = true;
        for (const auto& l : thread_results) {
            if (l.result.valid_count == 0) continue;
            double score = W1 * norm(l.result.m1, g_mi1, g_ma1) + W2 * norm(l.result.m2, g_mi2, g_ma2) + W3 * norm(l.result.m3, g_mi3, g_ma3);
            if (first || score < final_best.final_score - 1e-9) {
                final_best = l.result; final_best.final_score = score; first = false;
            } else if (std::abs(score - final_best.final_score) <= 1e-9) {
                final_best.best_count += l.result.best_count;
            }
        }

        py_result["assignment"] = final_best.best_assignment;
        py_result["final_score"] = final_best.final_score;
        py_result["m1"] = final_best.m1; py_result["m2"] = final_best.m2; py_result["m3"] = final_best.m3;
        py_result["valid_count"] = total_valid; py_result["best_count"] = final_best.best_count;
        py_result["group_edge_counts"] = final_best.group_edge_counts;
        py_result["node_group_distribution"] = final_best.node_group_distribution;

        py::list removal_list;
        for (const auto& d : final_best.group_removal_details) {
            py::dict d_dict; d_dict["dist"] = d.dist; d_dict["nodeA"] = d.nodeA; d_dict["nodeB"] = d.nodeB;
            removal_list.append(d_dict);
        }
        py_result["group_removal_details"] = removal_list;
    }
    return py_result;
}

PYBIND11_MODULE(graph_cpp_core, m) {
    m.def("search_best_assignment", &search_best_assignment);
}