import time
from PySide6.QtCore import QThread, Signal
import graph_cpp_core

class SearchWorker(QThread):
    progress_updated = Signal(int, str)               
    score_updated = Signal(float)                     
    valid_updated = Signal(int) # 【新增】即時更新合法數量                     
    log_msg = Signal(str)                             
    search_finished = Signal(object, int, int, float) 

    def __init__(self, k, f, edges_data, nodes, weights): 
        super().__init__()
        self.k = k
        self.f = f 
        self.edges_data = edges_data
        self.nodes = nodes
        self.weights = weights
        self._is_running = True 

    def stop(self):
        self._is_running = False

    def format_time(self, seconds):
        if seconds < 60: 
            return f"{int(seconds)}s"
        if seconds < 3600: 
            return f"{int(seconds // 60)}m {int(seconds % 60)}s"
        return f"{int(seconds // 3600)}h {int((seconds % 3600) // 60)}m"

    def run(self):
        N_count = len(self.nodes)
        E_count = len(self.edges_data)
        # print(N_count,E_count)
        if E_count == 0:
            self.search_finished.emit(None, 0, 0, 0.0)
            return

        reduced_total = self.k ** max(0, E_count - 1)
        self.log_msg.emit(f"--------- 開始搜尋 ( {reduced_total:,} 種組合) ---------")
        

        start_time = time.time()
        last_update_time = start_time

        # 【修改】接收 C++ 傳來的第四個參數：current_valid_count
        def cpp_progress_callback(current_count, total_count, current_best_score, current_valid_count):
            nonlocal last_update_time
            now = time.time()
            
            if current_best_score >= 0:
                self.score_updated.emit(current_best_score)
                
            # 【新增】隨時發送目前找到的合法數量
            self.valid_updated.emit(current_valid_count)

            if now - last_update_time >= 0.2:
                elapsed = now - start_time
                pct = int((current_count / total_count) * 100) if total_count > 0 else 0
                speed = current_count / elapsed if elapsed > 0 else 0
                eta = (total_count - current_count) / speed if speed > 0 else 0
                
                text = f"檢查中: {current_count:,}/{total_count:,} ({pct}%) | 速率: {int(speed):,} c/s | 剩餘: {self.format_time(eta)}"
                self.progress_updated.emit(pct, text)
                last_update_time = now
                
            return self._is_running 

        id_map = {node: idx for idx, node in enumerate(self.nodes)}
        edges_list = [(id_map[u], id_map[v]) for u, v, _ in self.edges_data]
        weights_list = list(self.weights)

        result_dict = graph_cpp_core.search_best_assignment(
            self.k, 
            len(self.nodes), 
            edges_list, 
            weights_list, 
            self.f, 
            cpp_progress_callback
        )

        final_elapsed = time.time() - start_time
        
        if not self._is_running:
            self.progress_updated.emit(100, f"已中斷搜尋 | 總耗時: {self.format_time(final_elapsed)}")
        else:
            self.progress_updated.emit(100, f"C++ 搜尋結束 | 總耗時: {self.format_time(final_elapsed)}")

        if not result_dict:
            self.search_finished.emit(None, 0, 0, final_elapsed)
        else:
            valid_count = result_dict.pop("valid_count")
            best_count = result_dict.pop("best_count")
            self.search_finished.emit(result_dict, valid_count, best_count, final_elapsed)