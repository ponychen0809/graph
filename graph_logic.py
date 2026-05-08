import time
import itertools
from PySide6.QtCore import QThread, Signal

class SearchWorker(QThread):
    progress_updated = Signal(int, str) 
    log_msg = Signal(str)               
    search_finished = Signal(object, int, int, float) 

    def __init__(self, k, edges_data, nodes, weights):
        super().__init__()
        self.k = k
        self.edges_data = edges_data
        self.nodes = nodes
        self.weights = weights
        self._is_running = True 

    def stop(self):
        self._is_running = False

    def is_connected(self, edges_subset):
        if not self.nodes: return True
        adj = {node.node_id: [] for node in self.nodes}
        for u, v, _ in edges_subset:
            adj[u.node_id].append(v.node_id)
            adj[v.node_id].append(u.node_id)

        visited = set()
        def dfs(node_id):
            visited.add(node_id)
            for neighbor in adj[node_id]:
                if neighbor not in visited:
                    dfs(neighbor)

        if self.nodes:
            dfs(self.nodes[0].node_id)
        return len(visited) == len(self.nodes)

    def get_max_diameter(self, edges_subset):
        adj = {node.node_id: [] for node in self.nodes}
        for u, v, _ in edges_subset:
            adj[u.node_id].append(v.node_id)
            adj[v.node_id].append(u.node_id)

        max_diameter = 0
        for start_node in self.nodes:
            visited_dist = {start_node.node_id: 0}
            queue = [start_node.node_id]
            while queue:
                curr = queue.pop(0)
                curr_dist = visited_dist[curr]
                for neighbor in adj[curr]:
                    if neighbor not in visited_dist:
                        visited_dist[neighbor] = curr_dist + 1
                        queue.append(neighbor)
                        if visited_dist[neighbor] > max_diameter:
                            max_diameter = visited_dist[neighbor]
        return max_diameter

    def format_time(self, seconds):
        if seconds < 60: return f"{int(seconds)}s"
        if seconds < 3600: return f"{int(seconds//60)}m {int(seconds%60)}s"
        return f"{int(seconds//3600)}h {int((seconds%3600)//60)}m"

    def run(self):
        E_count = len(self.edges_data)
        reduced_total = self.k ** (E_count - 1)
        valid_solutions = []

        self.log_msg.emit(f"開始搜尋... (對稱性優化後需檢查 {reduced_total:,} 種可能)")
        
        start_time = time.time() 
        last_update_time = start_time
        count = 0

        for rest in itertools.product(range(self.k), repeat=E_count-1):
            if not self._is_running:
                break

            count += 1
            assignment = (0,) + rest 

            if count % 5000 == 0:
                now = time.time()
                elapsed = now - start_time
                if now - last_update_time >= 0.2:
                    pct = int((count / reduced_total) * 100)
                    speed = count / elapsed if elapsed > 0 else 0
                    eta = (reduced_total - count) / speed if speed > 0 else 0
                    text = f"檢查中: {count:,}/{reduced_total:,} ({pct}%) | 速率: {int(speed):,} c/s | 剩餘: {self.format_time(eta)}"
                    self.progress_updated.emit(pct, text)
                    last_update_time = now

            if len(set(assignment)) < self.k: continue

            is_valid = True
            diameters = []
            for g_remove in range(self.k):
                subset = [self.edges_data[i] for i, g in enumerate(assignment) if g != g_remove]
                if not self.is_connected(subset):
                    is_valid = False
                    break
                diameters.append(self.get_max_diameter(subset))
            
            if is_valid:
                group_sizes = [assignment.count(i) for i in range(self.k)]
                m1 = sum((s - E_count/self.k)**2 for s in group_sizes)
                m2 = 0
                for node in self.nodes:
                    node_counts = [0]*self.k
                    for i, (u, v, _) in enumerate(self.edges_data):
                        if u == node or v == node: node_counts[assignment[i]] += 1
                    avg_n = sum(node_counts)/self.k
                    m2 += sum((c - avg_n)**2 for c in node_counts)
                
                valid_solutions.append({
                    "assignment": assignment, "m1": m1, "m2": m2, "m3": max(diameters)
                })

        final_elapsed = time.time() - start_time
        self.progress_updated.emit(100, f"搜尋結束 | 總耗時: {self.format_time(final_elapsed)}")

        if not valid_solutions:
            self.search_finished.emit(None, 0, 0, final_elapsed)
            return

        m1_v, m2_v, m3_v = [s["m1"] for s in valid_solutions], [s["m2"] for s in valid_solutions], [s["m3"] for s in valid_solutions]
        mi1, ma1 = min(m1_v), max(m1_v)
        mi2, ma2 = min(m2_v), max(m2_v)
        mi3, ma3 = min(m3_v), max(m3_v)
        
        def norm(v, mi, ma): return (v - mi) / (ma - mi) if ma != mi else 0.0
        W1, W2, W3 = self.weights
        best_sol, best_score = None, float('inf')

        for sol in valid_solutions:
            score = W1*norm(sol["m1"],mi1,ma1) + W2*norm(sol["m2"],mi2,ma2) + W3*norm(sol["m3"],mi3,ma3)
            sol["final_score"] = score
            if score < best_score:
                best_score = score
                best_sol = sol

        best_count = sum(1 for s in valid_solutions if abs(s["final_score"] - best_score) < 1e-9)
        self.search_finished.emit(best_sol, len(valid_solutions), best_count, final_elapsed)