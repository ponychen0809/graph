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
        self.setWindowTitle("Python Graph Editor - 最佳平衡容錯分析 (高效優化版)")
        self.resize(1300, 850)
        self.nodes, self.edges_data, self.node_id_counter, self.worker = [], [], 0, None
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # --- Top Layout (原本的功能按鈕) ---
        top_layout = QHBoxLayout()
        self.add_node_btn = self.create_btn(top_layout, "新增節點 (+)", self.add_new_node)
        self.arrange_btn = self.create_btn(top_layout, "自動排列", self.arrange_nodes_circle)
        top_layout.addWidget(QLabel(" 分組(K)"))
        self.k_input = QSpinBox()
        self.k_input.setRange(2, 5); self.k_input.setValue(2); self.k_input.setFixedSize(80, 40)
        self.k_input.valueChanged.connect(self.update_stats_and_k_limit)
        top_layout.addWidget(self.k_input)
        self.search_btn = self.create_btn(top_layout, "搜尋", self.start_background_search, "#ffd700")
        self.stop_btn = self.create_btn(top_layout, "停止", self.stop_background_search, "#ff4c4c", text_color="white")
        self.edst_btn = self.create_btn(top_layout, "計算不相交生成樹", self.calculate_max_edst, "#2ecc71", text_color="white")
        
        self.search_btn.setFixedSize(40, 30)
        self.edst_btn.setFixedSize(100, 30)
        self.stop_btn.setFixedSize(40, 30)

        top_layout.addStretch()
        main_layout.addLayout(top_layout)

        # --- Weight Layout (權重設定) ---
        weight_layout = QHBoxLayout()
        self.w1_i = self.create_weight(weight_layout, "W1 數量:", 0.3)
        self.w2_i = self.create_weight(weight_layout, "W2 拓樸:", 0.3)
        self.w3_i = self.create_weight(weight_layout, "W3 效能:", 0.4)
        weight_layout.addStretch()
        main_layout.addLayout(weight_layout)

        # --- NEW: Visibility Control Layout (新增的隱藏/還原工具列) ---
        visibility_layout = QHBoxLayout()
        visibility_layout.addWidget(QLabel("顯示控制: "))
        self.hide_group_input = QSpinBox()
        self.hide_group_input.setRange(1, 2) # 預設會隨 K 值連動
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
        main_layout.addWidget(self.view, stretch=7)

        # --- Log & Stats ---
        info_layout = QHBoxLayout()
        self.log_te = self.create_te(info_layout, "System Log", 4)
        self.matrix_te = self.create_te(info_layout, "Adjacency Matrix", 2, mono=True)
        
        stat_box = QVBoxLayout(); stat_box.addWidget(QLabel("即時統計資訊"))
        self.st_n = QLabel("節點數量: 0"); self.st_e = QLabel("連線數量: 0")
        self.st_t = QLabel("可能分法: 0"); self.st_v = QLabel("合法分法:")
        for l in [self.st_n, self.st_e, self.st_t, self.st_v]:
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
        if mono: t.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        v.addWidget(t); layout.addLayout(v, stretch); return t

    def log_message(self, msg):
        self.log_te.append(msg); self.log_te.verticalScrollBar().setValue(self.log_te.verticalScrollBar().maximum())

    def update_stats_and_k_limit(self):
        """當 K 值改變時，同時更新統計與隱藏按鈕的上限"""
        k_val = self.k_input.value()
        self.hide_group_input.setRange(1, k_val)
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
        if n == 0:
            # self.matrix_te.setText("等待節點...")
            return
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
        self.st_v.setText("合法分法:"); self.st_v.setStyleSheet("color: blue; font-weight: bold;")

    def start_background_search(self):
        if not self.edges_data: return
        # 搜尋前還原所有邊的屬性
        for _, _, l in self.edges_data: 
            l.setPen(QPen(Qt.GlobalColor.red, 2))
            l.setVisible(True)
            if hasattr(l, 'group_id'): del l.group_id

        self.set_ui_enabled(False); self.p_bar.setVisible(True); self.p_bar.setValue(0)
        w_raw = (self.w1_i.value(), self.w2_i.value(), self.w3_i.value())
        total_w = sum(w_raw)
        weights = (0.33, 0.33, 0.33) if total_w == 0 else [w/total_w for w in w_raw]
        self.worker = SearchWorker(self.k_input.value(), self.edges_data, self.nodes, weights)
        self.worker.progress_updated.connect(lambda p, t: (self.p_bar.setValue(p), self.p_bar.setFormat(t)))
        self.worker.log_msg.connect(self.log_message)
        self.worker.search_finished.connect(self.on_search_finished); self.worker.start()

    def stop_background_search(self):
        if self.worker: self.worker.stop(); self.stop_btn.setEnabled(False)

    def set_ui_enabled(self, e):
        # 搜尋時禁用顯示控制按鈕
        for w in [self.add_node_btn, self.arrange_btn, self.search_btn, self.edst_btn, 
                  self.k_input, self.w1_i, self.w2_i, self.w3_i, self.view, self.hide_btn, self.show_all_btn]:
            w.setEnabled(e)
        self.stop_btn.setEnabled(not e)

    def on_search_finished(self, best, valid, b_count, elapsed):
        self.p_bar.setVisible(False)
        self.set_ui_enabled(True)
        self.st_v.setText(f"合法分法: {valid:,}")
        self.st_v.setStyleSheet(f"color: {'green' if valid > 0 else 'red'}; font-weight: bold;")
        self.log_message(f"--- 搜尋結束 (耗時 {elapsed:.2f}s) ---")
        
        if valid > 0 and best:
            # 取得 C++ 傳回來的分數資訊
            score = best.get("final_score", 0.0)
            m1 = best.get("m1", 0.0)
            m2 = best.get("m2", 0.0)
            m3 = best.get("m3", 0.0)
            
            # 在 Log 區塊印出詳細分數
            self.log_message(f"[結果] 發現 {valid:,} 種合法解 | 同分最佳解 {b_count:,} 種")
            self.log_message(f"[最佳評分] {score:.6f} (越低越好)")
            self.log_message(f" ├ M1 (數量方差): {m1:.2f}")
            self.log_message(f" ├ M2 (拓樸方差): {m2:.2f}")
            self.log_message(f" └ M3 (最大直徑): {m3}")
            
            # 替最佳解的連線著色
            palette = [Qt.GlobalColor.blue, Qt.GlobalColor.green, Qt.GlobalColor.magenta, Qt.GlobalColor.darkYellow, Qt.GlobalColor.cyan]
            for i, group in enumerate(best["assignment"]): 
                self.edges_data[i][2].setPen(QPen(palette[group % len(palette)], 3))

    # --- NEW: Visibility Logic ---
    def hide_selected_group(self):
        target = self.hide_group_input.value() - 1 # UI 是 1-based, 程式是 0-based
        count = 0
        for _, _, link in self.edges_data:
            if hasattr(link, 'group_id') and link.group_id == target:
                link.setVisible(False)
                count += 1
        
        # if count > 0:
        #     self.log_message(f"[UI] 已暫時隱藏第 {target+1} 組的邊 (共 {count} 條)")
        # else:
        #     self.log_message(f"[警告] 找不到第 {target+1} 組的分組資訊，請先執行搜尋。")

    def show_all_edges(self):
        for _, _, link in self.edges_data:
            link.setVisible(True)
        # self.log_message("[UI] 已還原所有邊的顯示。")

    def calculate_max_edst(self):
        # 原本的 EDST 邏輯不變，但同樣加入還原所有顯示的動作
        if len(self.nodes) < 2:
            self.log_message("[EDST] 節點不足，無法分析。")
            return
        
        for _, _, l in self.edges_data: l.setVisible(True)

        V = [n.node_id for n in self.nodes]
        E_with_links = [(u.node_id, v.node_id, l) for u, v, l in self.edges_data]

        def get_parent(parent, i):
            if parent[i] == i: return i
            parent[i] = get_parent(parent, parent[i])
            return parent[i]

        def is_circuit_free(edges_subset, vertices):
            parent = {n: n for n in vertices}
            for u, v, _ in edges_subset:
                root_u, root_v = get_parent(parent, u), get_parent(parent, v)
                if root_u == root_v: return False
                parent[root_u] = root_v
            return True

        max_k = 0
        best_forests = []
        theoretical_limit = len(E_with_links) // (len(V) - 1)

        for k in range(1, theoretical_limit + 1):
            current_forests = [[] for _ in range(k)]
            for e_tuple in E_with_links:
                for f_idx in range(k):
                    if is_circuit_free(current_forests[f_idx] + [e_tuple], V):
                        current_forests[f_idx].append(e_tuple)
                        break
            
            full_trees = [f for f in current_forests if len(f) == len(V) - 1]
            if len(full_trees) >= k:
                max_k = k
                best_forests = full_trees
            else:
                break

        for _, _, l in self.edges_data:
            l.setPen(QPen(Qt.GlobalColor.lightGray, 1, Qt.PenStyle.DashLine))

        self.log_message(f"--- 最大不相交生成樹分析 ---")
        self.log_message(f"此圖包含 {max_k} 棵邊不相交生成樹。")
        
        if max_k > 0:
            palette = [Qt.GlobalColor.blue, Qt.GlobalColor.green, Qt.GlobalColor.magenta, 
                       Qt.GlobalColor.darkYellow, Qt.GlobalColor.cyan, Qt.GlobalColor.darkRed]
            for tree_idx, tree_edges in enumerate(best_forests):
                color = palette[tree_idx % len(palette)]
                for _, _, link_obj in tree_edges:
                    link_obj.setPen(QPen(color, 3))
        else:
            self.log_message(f"警告：連一棵完整的生成樹都找不出來。")