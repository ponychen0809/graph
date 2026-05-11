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
#include <mutex>
#include <utility> 

namespace py = pybind11;

struct DiameterInfo {
    int dist = 0;
    int nodeA = -1;
    int nodeB = -1;
};

struct SearchResult {
    std::vector<int> best_assignment;
    int valid_count = 0;
    int best_count = 0;
    double m1 = 0, m2 = 0, m3 = 0, final_score = 0;

    std::vector<int> group_edge_counts;
    std::vector<std::vector<int>> node_group_distribution;
    std::vector<std::pair<int, DiameterInfo>> group_removal_details; 
};

struct GlobalState {
    std::mutex mtx;
    double mi1 = 1e30, ma1 = -1e30;
    double mi2 = 1e30, ma2 = -1e30;
    double mi3 = 1e30, ma3 = -1e30;
    SearchResult best_result;
    double best_score = 1e30;
    bool has_best = false;
    unsigned long long total_valid = 0;
};

struct BFSResult {
    int dist; int furthest_node; int visited_count;
};

BFSResult get_furthest_info(int num_nodes, const std::vector<std::vector<int>>& adj, int start_node) {
    std::vector<int> dists(num_nodes, -1);
    std::queue<int> q; q.push(start_node);
    dists[start_node] = 0;
    int visited = 1; int max_d = 0; int furthest = start_node;

    while(!q.empty()) {
        int u = q.front(); q.pop();
        if (dists[u] > max_d) { max_d = dists[u]; furthest = u; }
        for(int v : adj[u]) {
            if(dists[v] == -1) { dists[v] = dists[u] + 1; visited++; q.push(v); }
        }
    }
    return {max_d, furthest, visited};
}

inline double norm(double v, double mi, double ma) {
    return (ma > mi) ? (v - mi) / (ma - mi) : 0.0;
}

void idx_to_assignment(unsigned long long idx, int k, int E, std::vector<int>& assignment) {
    assignment[0] = 0;
    for (int i = E - 1; i > 0; --i) { assignment[i] = idx % k; idx /= k; }
}

py::dict search_best_assignment(
    int k, int num_nodes, 
    std::vector<std::pair<int, int>> edges, 
    std::vector<double> weights,
    int fault_tolerance, 
    // 【修改】加入第 4 個參數 (unsigned long long) 用來傳遞合法解數量
    std::function<bool(unsigned long long, unsigned long long, double, unsigned long long)> progress_callback
) {
    int E = edges.size();
    if (E == 0 || num_nodes == 0) return py::dict();

    int target_mask = (1 << k) - 1;
    std::vector<int> failure_masks;
    for (int i = 1; i <= target_mask; ++i) {
        int bits = 0;
        for (int j = 0; j < k; ++j) {
            if (i & (1 << j)) bits++;
        }
        if (bits == fault_tolerance) {
            failure_masks.push_back(i); 
        }
    }
    if (failure_masks.empty()) {
        for (int i = 0; i < k; ++i) failure_masks.push_back(1 << i);
    }

    unsigned long long total_combinations = std::pow(k, std::max(0, E - 1));
    unsigned int num_threads = std::thread::hardware_concurrency();
    if (num_threads == 0) num_threads = 4;

    unsigned long long chunk_size = total_combinations / num_threads;
    std::atomic<unsigned long long> global_count(0);
    std::atomic<bool> global_stop_flag(false);
    
    GlobalState global_state;
    std::vector<std::thread> threads;

    double W1 = weights[0], W2 = weights[1], W3 = weights[2];

    py::gil_scoped_release release;

    for (unsigned int t = 0; t < num_threads; ++t) {
        threads.emplace_back([&, t]() {
            unsigned long long start_idx = t * chunk_size;
            unsigned long long end_idx = (t == num_threads - 1) ? total_combinations : (t + 1) * chunk_size;
            
            std::vector<int> assignment(E, 0);
            idx_to_assignment(start_idx, k, E, assignment);
            std::vector<std::vector<int>> adj(num_nodes);
            
            unsigned long long local_loop_count = 0;
            double local_mi1 = 1e30, local_ma1 = -1e30;
            double local_mi2 = 1e30, local_ma2 = -1e30;
            double local_mi3 = 1e30, local_ma3 = -1e30;
            int local_batch_valid = 0;
            
            bool has_local_best = false;
            SearchResult local_best;
            
            double cached_mi1 = 1e30, cached_ma1 = -1e30;
            double cached_mi2 = 1e30, cached_ma2 = -1e30;
            double cached_mi3 = 1e30, cached_ma3 = -1e30;

            auto flush_local_state = [&]() {
                std::lock_guard<std::mutex> lock(global_state.mtx);
                if (local_batch_valid > 0) {
                    global_state.mi1 = std::min(global_state.mi1, local_mi1);
                    global_state.ma1 = std::max(global_state.ma1, local_ma1);
                    global_state.mi2 = std::min(global_state.mi2, local_mi2);
                    global_state.ma2 = std::max(global_state.ma2, local_ma2);
                    global_state.mi3 = std::min(global_state.mi3, local_mi3);
                    global_state.ma3 = std::max(global_state.ma3, local_ma3);
                    global_state.total_valid += local_batch_valid; // 這裡不斷累加全域數量
                    
                    local_batch_valid = 0;
                    local_mi1 = 1e30; local_ma1 = -1e30;
                    local_mi2 = 1e30; local_ma2 = -1e30;
                    local_mi3 = 1e30; local_ma3 = -1e30;
                }
                
                if (has_local_best) {
                    if (global_state.has_best) {
                        global_state.best_score = W1 * norm(global_state.best_result.m1, global_state.mi1, global_state.ma1) + 
                                                  W2 * norm(global_state.best_result.m2, global_state.mi2, global_state.ma2) + 
                                                  W3 * norm(global_state.best_result.m3, global_state.mi3, global_state.ma3);
                    }
                    double actual_local_score = W1 * norm(local_best.m1, global_state.mi1, global_state.ma1) + 
                                                W2 * norm(local_best.m2, global_state.mi2, global_state.ma2) + 
                                                W3 * norm(local_best.m3, global_state.mi3, global_state.ma3);
                                                
                    if (!global_state.has_best || actual_local_score < global_state.best_score - 1e-9) {
                        global_state.best_result = local_best;
                        global_state.best_score = actual_local_score;
                        global_state.has_best = true;
                    } else if (std::abs(actual_local_score - global_state.best_score) <= 1e-9) {
                        global_state.best_result.best_count += local_best.best_count;
                    }
                    has_local_best = false; 
                }
                
                cached_mi1 = global_state.mi1; cached_ma1 = global_state.ma1;
                cached_mi2 = global_state.mi2; cached_ma2 = global_state.ma2;
                cached_mi3 = global_state.mi3; cached_ma3 = global_state.ma3;
            };

            for (unsigned long long idx = start_idx; idx < end_idx; ++idx) {
                if (global_stop_flag.load(std::memory_order_relaxed)) break;
                local_loop_count++;
                
                int mask = 0; for (int g : assignment) mask |= (1 << g);
                
                if (mask == target_mask) {
                    bool is_valid = true;
                    int global_max_dia = 0;
                    std::vector<std::pair<int, DiameterInfo>> current_diameters;

                    for (int f_mask : failure_masks) {
                        for(int i = 0; i < num_nodes; ++i) adj[i].clear();
                        for (int i = 0; i < E; ++i) {
                            if ((f_mask & (1 << assignment[i])) == 0) {
                                adj[edges[i].first].push_back(edges[i].second);
                                adj[edges[i].second].push_back(edges[i].first);
                            }
                        }

                        BFSResult check = get_furthest_info(num_nodes, adj, 0);
                        if (check.visited_count < num_nodes) { is_valid = false; break; }

                        DiameterInfo dia;
                        for (int n = 0; n < num_nodes; ++n) {
                            BFSResult res = get_furthest_info(num_nodes, adj, n);
                            if (res.dist > dia.dist) { dia.dist = res.dist; dia.nodeA = n; dia.nodeB = res.furthest_node; }
                        }
                        current_diameters.push_back({f_mask, dia});
                        global_max_dia = std::max(global_max_dia, dia.dist);
                    }

                    if (is_valid) {
                        local_batch_valid++;
                        std::vector<int> group_counts(k, 0); for (int g : assignment) group_counts[g]++;
                        double m1 = 0; double exp = (double)E / k; for (int c : group_counts) m1 += (c - exp) * (c - exp);

                        double m2 = 0; std::vector<std::vector<int>> node_dist(num_nodes, std::vector<int>(k, 0));
                        for (int n = 0; n < num_nodes; ++n) {
                            for (int i = 0; i < E; ++i) { if (edges[i].first == n || edges[i].second == n) node_dist[n][assignment[i]]++; }
                            double avg = (double)std::accumulate(node_dist[n].begin(), node_dist[n].end(), 0) / k;
                            for (int c : node_dist[n]) m2 += (c - avg) * (c - avg);
                        }
                        double m3 = global_max_dia;

                        local_mi1 = std::min(local_mi1, m1); local_ma1 = std::max(local_ma1, m1);
                        local_mi2 = std::min(local_mi2, m2); local_ma2 = std::max(local_ma2, m2);
                        local_mi3 = std::min(local_mi3, m3); local_ma3 = std::max(local_ma3, m3);

                        double e_mi1 = std::min(local_mi1, cached_mi1); double e_ma1 = std::max(local_ma1, cached_ma1);
                        double e_mi2 = std::min(local_mi2, cached_mi2); double e_ma2 = std::max(local_ma2, cached_ma2);
                        double e_mi3 = std::min(local_mi3, cached_mi3); double e_ma3 = std::max(local_ma3, cached_ma3);

                        double cand_score = W1 * norm(m1, e_mi1, e_ma1) + W2 * norm(m2, e_mi2, e_ma2) + W3 * norm(m3, e_mi3, e_ma3);
                        double curr_score = 1e30;
                        if (has_local_best) {
                            curr_score = W1 * norm(local_best.m1, e_mi1, e_ma1) + W2 * norm(local_best.m2, e_mi2, e_ma2) + W3 * norm(local_best.m3, e_mi3, e_ma3);
                        }

                        if (!has_local_best || cand_score < curr_score - 1e-9) {
                            local_best.best_assignment = assignment;
                            local_best.m1 = m1; local_best.m2 = m2; local_best.m3 = m3;
                            local_best.group_edge_counts = group_counts;
                            local_best.node_group_distribution = node_dist;
                            local_best.group_removal_details = current_diameters;
                            local_best.best_count = 1;
                            has_local_best = true;
                        } else if (std::abs(cand_score - curr_score) <= 1e-9) {
                            local_best.best_count++;
                        }
                    }
                }

                int i = E - 1; while (i > 0) { assignment[i]++; if (assignment[i] < k) break; assignment[i] = 0; i--; }
                
                if (local_loop_count % 100000 == 0) {
                    global_count.fetch_add(100000, std::memory_order_relaxed);
                    flush_local_state();
                }
            }
            
            global_count.fetch_add(local_loop_count % 100000, std::memory_order_relaxed);
            flush_local_state();
        });
    }

    while (true) {
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
        unsigned long long current = global_count.load(std::memory_order_relaxed);
        
        double current_best = -1.0;
        unsigned long long current_valid = 0; // 【新增】抓取目前的合法總數
        
        {
            std::lock_guard<std::mutex> lock(global_state.mtx);
            if (global_state.has_best) {
                global_state.best_score = W1 * norm(global_state.best_result.m1, global_state.mi1, global_state.ma1) + 
                                          W2 * norm(global_state.best_result.m2, global_state.mi2, global_state.ma2) + 
                                          W3 * norm(global_state.best_result.m3, global_state.mi3, global_state.ma3);
                current_best = global_state.best_score;
            }
            current_valid = global_state.total_valid; // 從有鎖定保護的全域變數抓取
        }
        
        py::gil_scoped_acquire acquire;
        if (progress_callback) {
            // 【修改】將 current_valid 傳給 Python
            if (!progress_callback(current, total_combinations, current_best, current_valid)) {
                global_stop_flag.store(true);
            }
        }
        if (current >= total_combinations || global_stop_flag.load()) break;
    }

    for (auto& th : threads) if (th.joinable()) th.join();

    py::gil_scoped_acquire acquire;
    py::dict py_result;

    if (global_state.has_best) {
        global_state.best_score = W1 * norm(global_state.best_result.m1, global_state.mi1, global_state.ma1) + 
                                  W2 * norm(global_state.best_result.m2, global_state.mi2, global_state.ma2) + 
                                  W3 * norm(global_state.best_result.m3, global_state.mi3, global_state.ma3);

        py_result["assignment"] = global_state.best_result.best_assignment;
        py_result["final_score"] = global_state.best_score;
        py_result["m1"] = global_state.best_result.m1; 
        py_result["m2"] = global_state.best_result.m2; 
        py_result["m3"] = global_state.best_result.m3;
        py_result["valid_count"] = global_state.total_valid; 
        py_result["best_count"] = global_state.best_result.best_count;
        py_result["group_edge_counts"] = global_state.best_result.group_edge_counts;
        py_result["node_group_distribution"] = global_state.best_result.node_group_distribution;
        
        py::list removal_list;
        for (const auto& d : global_state.best_result.group_removal_details) {
            py::dict d_dict; 
            d_dict["mask"] = d.first; 
            d_dict["dist"] = d.second.dist; 
            d_dict["nodeA"] = d.second.nodeA; 
            d_dict["nodeB"] = d.second.nodeB;
            removal_list.append(d_dict);
        }
        py_result["group_removal_details"] = removal_list;
    }
    return py_result;
}

PYBIND11_MODULE(graph_cpp_core, m) {
    m.def("search_best_assignment", &search_best_assignment);
}