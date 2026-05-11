import time
from PySide6.QtCore import QThread, Signal
import graph_cpp_core

class SearchWorker(QThread):
    # 定義與 UI 溝通的訊號
    progress_updated = Signal(int, str)               # 更新進度條與文字 (百分比, 提示字串)
    score_updated = Signal(float)                     # 即時更新當前最佳分數 (新增)
    log_msg = Signal(str)                             # 傳送系統日誌
    search_finished = Signal(object, int, int, float) # 搜尋結束 (最佳解, 合法數量, 同分數數量, 耗時)

    def __init__(self, k, edges_data, nodes, weights):
        super().__init__()
        self.k = k
        self.edges_data = edges_data
        self.nodes = nodes
        self.weights = weights
        self._is_running = True 

    def stop(self):
        """外部呼叫此方法來中斷搜尋"""
        self._is_running = False

    def format_time(self, seconds):
        """將秒數格式化為易讀的字串"""
        if seconds < 60: 
            return f"{int(seconds)}s"
        if seconds < 3600: 
            return f"{int(seconds // 60)}m {int(seconds % 60)}s"
        return f"{int(seconds // 3600)}h {int((seconds % 3600) // 60)}m"

    def run(self):
        E_count = len(self.edges_data)
        if E_count == 0:
            self.search_finished.emit(None, 0, 0, 0.0)
            return

        # 第 0 條邊固定為第 0 組 (對稱優化)
        reduced_total = self.k ** max(0, E_count - 1)
        self.log_msg.emit(f"啟動 C++ 加速引擎... (需檢查 {reduced_total:,} 種組合)")
        
        start_time = time.time()
        last_update_time = start_time

        def cpp_progress_callback(current_count, total_count, current_best_score):
            """這個函式會由 C++ 引擎頻繁呼叫，用來回報進度與當前最佳分數"""
            nonlocal last_update_time
            now = time.time()
            
            # 若 C++ 有找到合法解，即時發送分數更新 UI
            if current_best_score >= 0:
                # print(current_best_score)
                self.score_updated.emit(current_best_score)

            # 為了避免 UI 卡頓，限制每 0.2 秒更新一次介面
            if now - last_update_time >= 0.2:
                elapsed = now - start_time
                pct = int((current_count / total_count) * 100) if total_count > 0 else 0
                speed = current_count / elapsed if elapsed > 0 else 0
                eta = (total_count - current_count) / speed if speed > 0 else 0
                
                text = f"檢查中: {current_count:,}/{total_count:,} ({pct}%) | 速率: {int(speed):,} c/s | 剩餘: {self.format_time(eta)}"
                self.progress_updated.emit(pct, text)
                last_update_time = now
                
            # 回傳 False 就會通知 C++ 停止計算
            return self._is_running 

        # 將介面的 Node 轉換為純數字 ID 交給 C++
        id_map = {node: idx for idx, node in enumerate(self.nodes)}
        edges_list = [(id_map[u], id_map[v]) for u, v, _ in self.edges_data]
        weights_list = list(self.weights)

        # 呼叫 C++ 核心執行搜尋
        result_dict = graph_cpp_core.search_best_assignment(
            self.k, 
            len(self.nodes), 
            edges_list, 
            weights_list, 
            cpp_progress_callback
        )

        final_elapsed = time.time() - start_time
        
        # 判斷是自然結束還是被使用者中斷
        if not self._is_running:
            self.progress_updated.emit(100, f"已中斷搜尋 | 總耗時: {self.format_time(final_elapsed)}")
        else:
            self.progress_updated.emit(100, f"C++ 搜尋結束 | 總耗時: {self.format_time(final_elapsed)}")

        # 回傳最終結果給 UI
        if not result_dict:
            self.search_finished.emit(None, 0, 0, final_elapsed)
        else:
            valid_count = result_dict.pop("valid_count")
            best_count = result_dict.pop("best_count")
            self.search_finished.emit(result_dict, valid_count, best_count, final_elapsed)