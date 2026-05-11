import math
from PySide6.QtWidgets import (QGraphicsView, QGraphicsScene, QMainWindow, QWidget, 
                               QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit, 
                               QLabel, QSpinBox, QDoubleSpinBox, QProgressBar)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPen, QFont, QPainter

from graph_items import Node, Link
from graph_logic import SearchWorker

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Python Graph Editor - 最佳平衡容錯分析")
        self.resize(1300, 850)
        self.nodes, self.edges_data, self.node_id_counter, self.worker = [], [], 0, None
        self.current_assignment = None
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # --- Top Layout ---
        top_layout = QHBoxLayout()
        self.add_node_btn = self.create_btn(top_layout, "新增節點 (+)", self.add_new_node)
        
        # 【修改】改為「清空全部」按鈕
        self.clear_btn = self.create_btn(top_layout, "清空全部", self.clear_all_items, "#e74c3c", "white")
        
        self.arrange_btn = self.create_btn(top_layout, "自動排列", self.arrange_nodes_circle)
        
        top_layout.addWidget(QLabel(" 分組(K)"))
        self.k_input = QSpinBox()
        self.k_input.setRange(2, 5); self.k_input.setValue(2); self.k_input.setFixedSize(80, 40)
        self.k_input.valueChanged.connect(self.update_stats_and_k_limit)
        top_layout.addWidget(self.k_input)

        top_layout.addWidget(QLabel(" 容忍斷線(F)"))
        self.f_input = QSpinBox()
        self.f_input.setRange(1, 1); self.f_input.setValue(1); self.f_input.setFixedSize(80, 40)
        self.f_input.valueChanged.connect(self.update_stats_view)
        top_layout.addWidget(self.f_input)

        self.search_btn = self.create_btn(top_layout, "搜尋", self.start_background_search, "#ffd700")
        self.stop_btn = self.create_btn(top_layout, "停止", self.stop_background_search, "#ff4c4c", text_color="white")
        self.edst_btn = self.create_btn(top_layout, "計算不相交生成樹", self.calculate_max_edst, "#2ecc71", text_color="white")
        
        self.search_btn.setFixedSize(40, 30)
        self.edst_btn.setFixedSize(100, 30)
        self.stop_btn.setFixedSize(40, 30)
        self.clear_btn.setFixedSize(80, 30) # 稍微加寬一點

        top_layout.addStretch()
        main_layout.addLayout(top_layout)

        # --- Weight Layout ---
        weight_layout = QHBoxLayout()
        self.w1_i = self.create_weight(weight_layout, "W1 數量:", 0.3)
        self.w2_i = self.create_weight(weight_layout, "W2 拓樸:", 0.3)
        self.w3_i = self.create_weight(weight_layout, "W3 效能:", 0.4)
        weight_layout.addStretch()
        main_layout.addLayout(weight_layout)

        # --- Visibility Control Layout ---
        visibility_layout = QHBoxLayout()
        visibility_layout.addWidget(QLabel("顯示控制: "))
        self.hide_group_input = QSpinBox()
        self.hide_group_input.setRange(1, 2)
        self.hide_group_input.setFixedSize(80, 30)
        visibility_layout.addWidget(self.hide_group_input)
        
        self.hide_btn = self.create_btn(visibility_layout, "隱藏", self.hide_selected_group, "#95a5a6", "white")
        self.show_all_btn = self.create_btn(visibility_layout, "還原", self.show_all_edges, "#34495e", "white")
        self.show_all_btn.setFixedSize(40, 30)
        self.hide_btn.setFixedSize(40, 30)
        visibility_layout.addStretch()
        main_layout.addLayout(visibility_layout)

        # --- Progress Bar ---
        self.p_bar = QProgressBar()
        self.p_bar.setVisible(False); self.p_bar.setRange(0, 100); self.p_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.p_bar)

        # --- Scene & View ---
        self.scene = QGraphicsScene(); self.scene.setSceneRect(0, 0, 1000, 800)
        self.view = QGraphicsView(self.scene); self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        main_layout.addWidget(self.view, stretch=5)

        # --- Log & Stats ---
        info_layout = QHBoxLayout()
        self.log_te = self.create_te(info_layout, "System Log", 4)
        self.matrix_te = self.create_te(info_layout, "Adjacency Matrix", 2, mono=True)
        
        stat_box = QVBoxLayout(); stat_box.addWidget(QLabel("即時統計資訊"))
        self.st_n = QLabel("節點數量: 0"); self.st_e = QLabel("連線數量: 0")
        self.st_t = QLabel("可能分法: 0"); self.st_v = QLabel("合法分法:")
        self.st_score = QLabel("當前最佳評分: --") 
        
        for l in [self.st_n, self.st_e, self.st_t, self.st_v, self.st_score]:
            l.setFont(QFont("Arial", 11)); stat_box.addWidget(l)
        self.st_v.setStyleSheet("color: blue; font-weight: bold;")
        stat_box.addStretch(); info_layout.addLayout(stat_box, 1)
        main_layout.addLayout(info_layout, stretch=3)

        self.update_matrix_view(); self.update_stats_view(); self.stop_btn.setEnabled(False)

    def create_btn(self, layout, txt, slot, bg=None, text_color="black"):
        b = QPushButton(txt); b.setFixedHeight(40); b.clicked.connect(slot)
        if bg: b.setStyleSheet(f"background-color: {bg}; color: {text_color}; font-weight: bold; border-radius: 5px;")
        layout.addWidget(b); return b

    def create_weight(self, layout, txt, val):
        layout.addWidget(QLabel(txt))
        s = QDoubleSpinBox(); s.setRange(0, 10); s.setSingleStep(0.1); s.setValue(val)
        layout.addWidget(s); return s

    def create_te(self, layout, title, stretch, mono=False):
        v = QVBoxLayout(); v.addWidget(QLabel(title))
        t = QTextEdit(); t.setReadOnly(True); t.setMinimumHeight(180)
        if mono: t.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        else: t.setFont(QFont("Segoe UI", 10))
        v.addWidget(t); layout.addLayout(v, stretch)
        return t

    def log_message(self, msg):
        self.log_te.append(msg); self.log_te.verticalScrollBar().setValue(self.log_te.verticalScrollBar().maximum())

    def update_stats_and_k_limit(self):
        k_val = self.k_input.value()
        self.hide_group_input.setRange(1, k_val)
        self.f_input.setRange(1, max(1, k_val - 1)) 
        self.update_stats_view()

    def add_new_node(self):
        self.node_id_counter += 1
        pos = self.view.mapToScene(self.view.viewport().rect().center())
        n = Node(pos.x(), pos.y(), self.node_id_counter - 1, self.log_message, self.create_new_link)
        self.scene.addItem(n); self.nodes.append(n)
        self.update_matrix_view(); self.update_stats_view()

    def create_new_link(self, na, nb):
        if any((u==na and v==nb) or (u==nb and v==na) for u,v,_ in self.edges_data): return
        l = Link(na, nb); self.scene.addItem(l); self.edges_data.append((na, nb, l))
        self.update_matrix_view(); self.update_stats_view()

    def arrange_nodes_circle(self):
        if not self.nodes: return
        c = self.view.mapToScene(self.view.viewport().rect().center())
        r = max(150, len(self.nodes) * 20)
        for i, n in enumerate(self.nodes):
            a = 2 * math.pi * i / len(self.nodes)
            n.setPos(c.x() + r * math.cos(a), c.y() + r * math.sin(a))

    def update_matrix_view(self):
        n = len(self.nodes)
        if n == 0: return
        id_m = {nd.node_id: i for i, nd in enumerate(self.nodes)}
        mt = [[0]*n for _ in range(n)]
        for u, v, _ in self.edges_data:
            if u.node_id in id_m and v.node_id in id_m:
                mt[id_m[u.node_id]][id_m[v.node_id]] = mt[id_m[v.node_id]][id_m[u.node_id]] = 1
        txt = "    " + " ".join([str(nd.node_id) for nd in self.nodes]) + "\n    " + "-"*(n*2) + "\n"
        for i, row in enumerate(mt): txt += f"{self.nodes[i].node_id} | " + " ".join(map(str, row)) + "\n"
        self.matrix_te.setText(txt)

    def update_stats_view(self):
        e, k = len(self.edges_data), self.k_input.value()
        self.st_n.setText(f"節點數量: {len(self.nodes)}")
        self.st_e.setText(f"連線數量: {e}")
        self.st_t.setText(f"可能分法: {k**e if e > 0 else 0:,}")
        self.st_v.setText("合法分法:")
        self.st_v.setStyleSheet("color: blue; font-weight: bold;")
        self.st_score.setText("當前最佳評分: --"); self.st_score.setStyleSheet("color: black;")

    def start_background_search(self):
        if not self.edges_data: return
        for _, _, l in self.edges_data: 
            l.setPen(QPen(Qt.GlobalColor.red, 2))
            l.setVisible(True)
            if hasattr(l, 'group_id'): del l.group_id

        self.set_ui_enabled(False); self.p_bar.setVisible(True); self.p_bar.setValue(0)
        self.st_v.setText("合法分法: 0")
        self.st_v.setStyleSheet("color: black; font-weight: bold;")
        self.st_score.setText("當前最佳評分: 計算中...")
        
        w_raw = (self.w1_i.value(), self.w2_i.value(), self.w3_i.value())
        total_w = sum(w_raw)
        weights = (0.33, 0.33, 0.33) if total_w == 0 else [w/total_w for w in w_raw]
        
        self.worker = SearchWorker(self.k_input.value(), self.f_input.value(), self.edges_data, self.nodes, weights)
        self.worker.progress_updated.connect(lambda p, t: (self.p_bar.setValue(p), self.p_bar.setFormat(t)))
        self.worker.log_msg.connect(self.log_message)
        self.worker.search_finished.connect(self.on_search_finished)
        self.worker.score_updated.connect(self.update_live_score)
        self.worker.valid_updated.connect(self.update_live_valid)
        self.worker.start()

    def update_live_score(self, score):
        if score >= 0:
            self.st_score.setText(f"當前最佳評分: {score:.6f}")
            self.st_score.setStyleSheet("color: #d35400; font-weight: bold;")

    def update_live_valid(self, valid_count):
        self.st_v.setText(f"合法分法: {valid_count:,}")
        self.st_v.setStyleSheet(f"color: {'green' if valid_count > 0 else 'black'}; font-weight: bold;")

    def stop_background_search(self):
        if self.worker: self.worker.stop(); self.stop_btn.setEnabled(False)

    def set_ui_enabled(self, e):
        # 【修改】禁用清單包含 clear_btn
        for w in [self.add_node_btn, self.clear_btn, self.arrange_btn, self.search_btn, self.edst_btn, 
                  self.k_input, self.f_input, self.w1_i, self.w2_i, self.w3_i, self.view, self.hide_btn, self.show_all_btn]:
            w.setEnabled(e)
        self.stop_btn.setEnabled(not e)

    def on_search_finished(self, best, valid, b_count, elapsed):
        self.p_bar.setVisible(False)
        self.set_ui_enabled(True)
        self.st_v.setText(f"合法分法: {valid:,}")
        self.st_v.setStyleSheet(f"color: {'green' if valid > 0 else 'red'}; font-weight: bold;")
        self.log_message(f"--------- 搜尋結束 (耗時 {elapsed:.2f}s) ---------")
        
        if valid > 0 and best:
            self.current_assignment = best["assignment"]
            score = best.get("final_score", 0.0)
            m1 = best.get("m1", 0.0); m2 = best.get("m2", 0.0); m3 = best.get("m3", 0.0) 
            self.st_score.setText(f"當前最佳評分: {score:.6f}")
            self.st_score.setStyleSheet("color: #d35400; font-weight: bold;")
            palette = [Qt.GlobalColor.blue, Qt.GlobalColor.green, Qt.GlobalColor.magenta, 
                       Qt.GlobalColor.darkYellow, Qt.GlobalColor.cyan]
            for i, group in enumerate(best["assignment"]): 
                link_item = self.edges_data[i][2]
                link_item.setPen(QPen(palette[group % len(palette)], 3))
                link_item.group_id = group

    def hide_selected_group(self):
        target = self.hide_group_input.value() - 1 
        count = 0
        for _, _, link in self.edges_data:
            if hasattr(link, 'group_id') and link.group_id == target:
                link.setVisible(False); count += 1
        if count > 0: self.log_message(f"[UI] 已暫時隱藏第 {target+1} 組的邊 (共 {count} 條)")
        else: self.log_message(f"[警告] 找不到第 {target+1} 組的分組資訊，請先執行搜尋。")

    def show_all_edges(self):
        for _, _, link in self.edges_data: link.setVisible(True)

    def calculate_max_edst(self):
        if len(self.nodes) < 2:
            self.log_message("[EDST] 節點不足，無法分析。")
            return
        for _, _, l in self.edges_data: l.setVisible(True)
        V_ids = [n.node_id for n in self.nodes]
        E_with_links = [(u.node_id, v.node_id, l) for u, v, l in self.edges_data]
        def get_path_in_forest(forest_edges, u, v):
            adj = {vid: [] for vid in V_ids}
            for e in forest_edges:
                adj[e[0]].append((e[1], e)); adj[e[1]].append((e[0], e))
            visited = {u}; queue = [(u, [])]; head = 0
            while head < len(queue):
                curr, path = queue[head]; head += 1
                if curr == v: return path
                for neighbor, edge in adj[curr]:
                    if neighbor not in visited:
                        visited.add(neighbor); queue.append((neighbor, path + [edge]))
            return []
        max_k = 0; best_forests = []; theoretical_limit = len(E_with_links) // (len(V_ids) - 1)
        for k in range(1, theoretical_limit + 1):
            forests = [[] for _ in range(k)]
            for e_new in E_with_links:
                added_greedily = False
                for i in range(k):
                    if not get_path_in_forest(forests[i], e_new[0], e_new[1]):
                        forests[i].append(e_new); added_greedily = True; break
                if added_greedily: continue
                queue = [e_new]; parent = {e_new: None}; target_edge = None; target_forest = None; head = 0
                while head < len(queue) and target_edge is None:
                    curr_e = queue[head]; head += 1
                    for i in range(k):
                        path = get_path_in_forest(forests[i], curr_e[0], curr_e[1])
                        if not path: target_edge = curr_e; target_forest = i; break
                        else:
                            for cycle_e in path:
                                if cycle_e not in parent: parent[cycle_e] = (curr_e, i); queue.append(cycle_e)
                if target_edge is not None:
                    curr = target_edge; forests[target_forest].append(curr)
                    while parent[curr] is not None:
                        prev_e, f_idx = parent[curr]
                        forests[f_idx].remove(curr); forests[f_idx].append(prev_e); curr = prev_e
            full_trees = [f for f in forests if len(f) == len(V_ids) - 1]
            if len(full_trees) == k: max_k = k; best_forests = full_trees
            else: break
        for _, _, l in self.edges_data: l.setPen(QPen(Qt.GlobalColor.lightGray, 1, Qt.PenStyle.DashLine))
        self.log_message(f"--- 最大不相交生成樹分析 ---")
        if max_k > 0:
            palette = [Qt.GlobalColor.blue, Qt.GlobalColor.green, Qt.GlobalColor.magenta, Qt.GlobalColor.darkYellow, Qt.GlobalColor.cyan, Qt.GlobalColor.darkRed]
            for tree_idx, tree_edges in enumerate(best_forests):
                color = palette[tree_idx % len(palette)]
                for _, _, l in tree_edges: l.setPen(QPen(color, 3))

    # ==========================================
    # 刪除功能與鍵盤監聽事件區塊
    # ==========================================
    def clear_all_items(self):
        """【新增】一鍵清空畫布上所有的節點與連線"""
        if not self.nodes and not self.edges_data:
            return
            
        self.scene.clear()
        self.nodes = []
        self.edges_data = []
        self.node_id_counter = 0 # 重置計數器
        self.current_assignment = None
        
        # self.log_message("[UI] 已清空所有節點與連線。")
        self.update_matrix_view()
        self.update_stats_view()

    def delete_selected_items(self):
        """處理刪除選取物件的邏輯（鍵盤 Del 鍵觸發）"""
        selected_items = self.scene.selectedItems()
        if not selected_items:
            return

        nodes_to_delete = []
        links_to_delete = []

        for item in selected_items:
            if isinstance(item, Node): nodes_to_delete.append(item)
            elif isinstance(item, Link): links_to_delete.append(item)

        edges_to_remove = []
        for u, v, link in self.edges_data:
            if link in links_to_delete or u in nodes_to_delete or v in nodes_to_delete:
                edges_to_remove.append((u, v, link))

        for u, v, link in edges_to_remove:
            if (u, v, link) in self.edges_data: self.edges_data.remove((u, v, link))
            if link in self.scene.items(): self.scene.removeItem(link)
            u.remove_link(link); v.remove_link(link)

        for node in nodes_to_delete:
            if node in self.nodes: self.nodes.remove(node)
            if node in self.scene.items(): self.scene.removeItem(node)

        if nodes_to_delete or edges_to_remove:
            # self.log_message(f"[UI] 已刪除選取的 {len(nodes_to_delete)} 個節點 與 {len(edges_to_remove)} 條連線。")
            self.update_matrix_view()
            self.update_stats_view()

    def keyPressEvent(self, event):
        """監聽鍵盤 Delete 或 Backspace 鍵"""
        if event.key() == Qt.Key.Key_Delete or event.key() == Qt.Key.Key_Backspace:
            self.delete_selected_items()
        else:
            super().keyPressEvent(event)