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
#include <mutex>

namespace py = pybind11;

struct SearchResult {
    std::vector<int> best_assignment;
    int valid_count = 0;
    int best_count = 0;
    double m1 = 0, m2 = 0, m3 = 0, final_score = 0;
};

// 輔助結構：用來儲存每個執行緒的「局部邊界」，以便最後統一計算
struct ThreadLocalBounds {
    double mi1 = std::numeric_limits<double>::max(), ma1 = std::numeric_limits<double>::lowest();
    double mi2 = std::numeric_limits<double>::max(), ma2 = std::numeric_limits<double>::lowest();
    double mi3 = std::numeric_limits<double>::max(), ma3 = std::numeric_limits<double>::lowest();
    SearchResult result;
};

int get_max_dist_and_check_connected(int num_nodes, const std::vector<std::vector<int>>& adj, int start_node, bool check_connected) {
    std::vector<int> dist(num_nodes, -1);
    std::queue<int> q;
    q.push(start_node);
    dist[start_node] = 0;
    int visited_count = 1;
    int max_d = 0;

    while(!q.empty()) {
        int u = q.front(); 
        q.pop();
        for(int v : adj[u]) {
            if(dist[v] == -1) {
                dist[v] = dist[u] + 1;
                max_d = std::max(max_d, dist[v]);
                visited_count++;
                q.push(v);
            }
        }
    }
    if (check_connected && visited_count < num_nodes) return -1; 
    return max_d;
}

inline double norm(double v, double mi, double ma) {
    return (ma != mi) ? (v - mi) / (ma - mi) : 0.0;
}

// 【新增】將 1D 的索引值，轉換為初始的分組陣列 (讓每個執行緒可以從指定的起點開始算)
void idx_to_assignment(unsigned long long idx, int k, int E, std::vector<int>& assignment) {
    assignment[0] = 0; // 對稱優化：第 0 條邊永遠是 0
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
    
    // 【核心】取得電腦的 CPU 執行緒數量 (例如 8 核 16 緒就會回傳 16)
    unsigned int num_threads = std::thread::hardware_concurrency();
    if (num_threads == 0) num_threads = 4; // 預防萬一

    // 分割任務：計算每個執行緒要負責多少種組合
    unsigned long long chunk_size = total_combinations / num_threads;
    
    // 全局原子變數，確保多執行緒安全
    std::atomic<unsigned long long> global_count(0);
    std::atomic<bool> global_stop_flag(false);
    
    // 儲存每個執行緒的計算結果
    std::vector<ThreadLocalBounds> thread_results(num_threads);
    std::vector<std::thread> threads;

    double W1 = weights[0], W2 = weights[1], W3 = weights[2];
    int target_mask = (1 << k) - 1;

    // 釋放 Python GIL
    py::gil_scoped_release release;

    // 啟動多執行緒
    for (unsigned int t = 0; t < num_threads; ++t) {
        threads.emplace_back([&, t]() {
            unsigned long long start_idx = t * chunk_size;
            unsigned long long end_idx = (t == num_threads - 1) ? total_combinations : (t + 1) * chunk_size;
            
            std::vector<int> assignment(E, 0);
            idx_to_assignment(start_idx, k, E, assignment); // 初始化該執行緒的起點
            std::vector<std::vector<int>> adj(num_nodes);
            
            ThreadLocalBounds& local = thread_results[t];
            unsigned long long local_loop_count = 0;

            for (unsigned long long idx = start_idx; idx < end_idx; ++idx) {
                if (global_stop_flag.load(std::memory_order_relaxed)) break; // 若收到停止訊號，立刻退出

                local_loop_count++;
                // 每個執行緒每跑一小段，就把進度加進去全局計數器
                if (local_loop_count % 100000 == 0) {
                    global_count.fetch_add(100000, std::memory_order_relaxed);
                }

                // --- 以下為原本的圖論檢查邏輯，但只存入 local 的變數中 ---
                int mask = 0;
                for (int g : assignment) mask |= (1 << g);
                
                if (mask == target_mask) {
                    bool is_valid = true;
                    int max_diameter = 0;

                    for (int g_remove = 0; g_remove < k; ++g_remove) {
                        for(int i = 0; i < num_nodes; ++i) adj[i].clear();
                        for (int i = 0; i < E; ++i) {
                            if (assignment[i] != g_remove) {
                                adj[edges[i].first].push_back(edges[i].second);
                                adj[edges[i].second].push_back(edges[i].first);
                            }
                        }

                        int d = get_max_dist_and_check_connected(num_nodes, adj, 0, true);
                        if (d == -1) { is_valid = false; break; }
                        max_diameter = std::max(max_diameter, d);

                        for (int n = 1; n < num_nodes; ++n) {
                            d = get_max_dist_and_check_connected(num_nodes, adj, n, false);
                            max_diameter = std::max(max_diameter, d);
                        }
                    }

                    if (is_valid) {
                        local.result.valid_count++;
                        std::vector<int> group_sizes(k, 0);
                        for (int g : assignment) group_sizes[g]++;
                        double m1 = 0; double expected_size = (double)E / k;
                        for (int s : group_sizes) m1 += (s - expected_size) * (s - expected_size);

                        double m2 = 0;
                        for (int n = 0; n < num_nodes; ++n) {
                            std::vector<int> node_counts(k, 0);
                            for (int i = 0; i < E; ++i) {
                                if (edges[i].first == n || edges[i].second == n) node_counts[assignment[i]]++;
                            }
                            double sum_counts = 0; for(int c : node_counts) sum_counts += c;
                            double avg_n = sum_counts / k;
                            for (int c : node_counts) m2 += (c - avg_n) * (c - avg_n);
                        }
                        double m3 = max_diameter;

                        // 更新局部邊界
                        local.mi1 = std::min(local.mi1, m1); local.ma1 = std::max(local.ma1, m1);
                        local.mi2 = std::min(local.mi2, m2); local.ma2 = std::max(local.ma2, m2);
                        local.mi3 = std::min(local.mi3, m3); local.ma3 = std::max(local.ma3, m3);

                        // 局部正規化計分
                        double current_best_score = W1 * norm(local.result.m1, local.mi1, local.ma1) + 
                                                    W2 * norm(local.result.m2, local.mi2, local.ma2) + 
                                                    W3 * norm(local.result.m3, local.mi3, local.ma3);
                        double candidate_score = W1 * norm(m1, local.mi1, local.ma1) + 
                                                 W2 * norm(m2, local.mi2, local.ma2) + 
                                                 W3 * norm(m3, local.mi3, local.ma3);

                        if (local.result.valid_count == 1 || candidate_score < current_best_score - 1e-9) {
                            local.result.best_assignment = assignment;
                            local.result.m1 = m1; local.result.m2 = m2; local.result.m3 = m3;
                            local.result.final_score = candidate_score; local.result.best_count = 1;
                        } else if (std::abs(candidate_score - current_best_score) <= 1e-9) {
                            local.result.best_count++; local.result.final_score = current_best_score;
                        } else {
                            local.result.final_score = current_best_score;
                        }
                    }
                }

                // 進位產生下一種組合
                int i = E - 1;
                while (i > 0) {
                    assignment[i]++;
                    if (assignment[i] < k) break;
                    assignment[i] = 0;
                    i--;
                }
            }
            // 補齊最後的零頭計數
            global_count.fetch_add(local_loop_count % 100000, std::memory_order_relaxed);
        });
    }

    // --- 主執行緒負責監控進度與回報 Python ---
    while (true) {
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
        unsigned long long current = global_count.load(std::memory_order_relaxed);
        
        {
            py::gil_scoped_acquire acquire;
            if (progress_callback) {
                bool keep_running = progress_callback(current, total_combinations);
                if (!keep_running) {
                    global_stop_flag.store(true, std::memory_order_relaxed); // 通知所有執行緒煞車
                }
            }
        }
        
        if (current >= total_combinations || global_stop_flag.load(std::memory_order_relaxed)) break;
    }

    // 等待所有執行緒完成收尾工作
    for (auto& th : threads) {
        if (th.joinable()) th.join();
    }

    // --- 收攏：全局大亂鬥 (找出絕對最佳解) ---
    py::gil_scoped_acquire acquire;
    py::dict py_result;
    
    int total_valid = 0;
    double global_mi1 = std::numeric_limits<double>::max(), global_ma1 = std::numeric_limits<double>::lowest();
    double global_mi2 = std::numeric_limits<double>::max(), global_ma2 = std::numeric_limits<double>::lowest();
    double global_mi3 = std::numeric_limits<double>::max(), global_ma3 = std::numeric_limits<double>::lowest();

    // 1. 統整出全域的 Max / Min
    for (const auto& local : thread_results) {
        total_valid += local.result.valid_count;
        if (local.result.valid_count > 0) {
            global_mi1 = std::min(global_mi1, local.mi1); global_ma1 = std::max(global_ma1, local.ma1);
            global_mi2 = std::min(global_mi2, local.mi2); global_ma2 = std::max(global_ma2, local.ma2);
            global_mi3 = std::min(global_mi3, local.mi3); global_ma3 = std::max(global_ma3, local.ma3);
        }
    }

    // 2. 利用全域標準，重新審查每個執行緒提報的最佳解，選出真正的第一名
    if (total_valid > 0) {
        SearchResult final_best;
        bool first = true;
        
        for (const auto& local : thread_results) {
            if (local.result.valid_count == 0) continue;
            
            double recalculated_score = W1 * norm(local.result.m1, global_mi1, global_ma1) + 
                                        W2 * norm(local.result.m2, global_mi2, global_ma2) + 
                                        W3 * norm(local.result.m3, global_mi3, global_ma3);
                                        
            if (first || recalculated_score < final_best.final_score - 1e-9) {
                final_best = local.result;
                final_best.final_score = recalculated_score;
                first = false;
            } else if (std::abs(recalculated_score - final_best.final_score) <= 1e-9) {
                final_best.best_count += local.result.best_count; // 同分則累加數量
            }
        }

        py_result["assignment"] = final_best.best_assignment;
        py_result["m1"] = final_best.m1; py_result["m2"] = final_best.m2; py_result["m3"] = final_best.m3;
        py_result["final_score"] = final_best.final_score;
        py_result["valid_count"] = total_valid; 
        py_result["best_count"] = final_best.best_count;
    }

    return py_result;
}

PYBIND11_MODULE(graph_cpp_core, m) {
    m.doc() = "Multi-Threaded High-performance C++ Graph Partition Solver";
    m.def("search_best_assignment", &search_best_assignment, "Finds the best graph partition");
}