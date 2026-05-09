import time
from PySide6.QtCore import QThread, Signal
import graph_cpp_core # 引入我們剛剛編譯好的 C++ 模組

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
        # 注意：因為目前運算完全交由 C++ 底層執行，一旦進入 C++ 函式後，
        # 在它算完之前 Python 無法中斷它。如果圖非常大，按下停止可能不會立刻反應。

    def format_time(self, seconds):
        if seconds < 60: return f"{int(seconds)}s"
        if seconds < 3600: return f"{int(seconds//60)}m {int(seconds%60)}s"
        return f"{int(seconds//3600)}h {int((seconds%3600)//60)}m"

    def run(self):
        import graph_cpp_core # 引入我們編譯好的 C++ 模組
        
        E_count = len(self.edges_data)
        if E_count == 0:
            self.search_finished.emit(None, 0, 0, 0.0)
            return

        reduced_total = self.k ** (E_count - 1)
        self.log_msg.emit(f"開始搜尋 (需檢查 {reduced_total:,} 種組合)")
        
        start_time = time.time()
        last_update_time = start_time

        # --- 【新增】準備傳給 C++ 的回呼函式 ---
        def cpp_progress_callback(current_count, total_count):
            nonlocal last_update_time
            now = time.time()
            
            # 控制更新頻率 (每 0.2 秒最多更新一次介面，避免 GUI 刷新太快卡頓)
            if now - last_update_time >= 0.2:
                elapsed = now - start_time
                pct = int((current_count / total_count) * 100) if total_count > 0 else 0
                speed = current_count / elapsed if elapsed > 0 else 0
                eta = (total_count - current_count) / speed if speed > 0 else 0
                
                text = f"檢查中: {current_count:,}/{total_count:,} ({pct}%) | 速率: {int(speed):,} c/s | 剩餘: {self.format_time(eta)}"
                self.progress_updated.emit(pct, text)
                last_update_time = now
                
            # 回傳 True 代表繼續執行，回傳 False 代表中斷 (使用者按了停止)
            return self._is_running

        # 1. 安全映射：將 node 對應為 0 ~ (num_nodes - 1) 的 index
        id_map = {node: idx for idx, node in enumerate(self.nodes)}
        edges_list = [(id_map[u], id_map[v]) for u, v, _ in self.edges_data]
        weights_list = list(self.weights)

        # 2. 直接呼叫 C++ 核心，並把 callback 傳進去
        result_dict = graph_cpp_core.search_best_assignment(
            self.k, len(self.nodes), edges_list, weights_list, cpp_progress_callback
        )

        final_elapsed = time.time() - start_time
        
        # 根據是否是被手動停止，顯示不同訊息
        if not self._is_running:
            self.progress_updated.emit(100, f"已中斷搜尋 | 總耗時: {self.format_time(final_elapsed)}")
        else:
            self.progress_updated.emit(100, f"C++ 搜尋結束 | 總耗時: {self.format_time(final_elapsed)}")

        # 3. 處理回傳結果
        if not result_dict:
            self.search_finished.emit(None, 0, 0, final_elapsed)
        else:
            valid_count = result_dict.pop("valid_count")
            best_count = result_dict.pop("best_count")
            self.search_finished.emit(result_dict, valid_count, best_count, final_elapsed)