from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsLineItem, QGraphicsSimpleTextItem
from PySide6.QtCore import Qt, QLineF
from PySide6.QtGui import QPen, QBrush, QFont

class Node(QGraphicsEllipseItem):
    def __init__(self, x, y, node_id, log_callback, create_link_callback):
        super().__init__(-20, -20, 40, 40)
        self.setPos(x, y)
        self.node_id = node_id 
        self.log_callback = log_callback
        self.create_link_callback = create_link_callback
        
        self.setBrush(QBrush(Qt.GlobalColor.cyan))
        self.setPen(QPen(Qt.GlobalColor.black, 2))
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        
        self.links = []       
        self.temp_line = None 
        self.is_dragging = False

        self.text_item = QGraphicsSimpleTextItem(str(self.node_id), self)
        font = QFont("Arial", 12, QFont.Weight.Bold)
        self.text_item.setFont(font)
        text_rect = self.text_item.boundingRect()
        self.text_item.setPos(-text_rect.width() / 2, -text_rect.height() / 2)

    def add_link(self, link):
        self.links.append(link)

    def remove_link(self, link):
        if link in self.links:
            self.links.remove(link)

    def itemChange(self, change, value):
        if change == QGraphicsEllipseItem.GraphicsItemChange.ItemPositionHasChanged:
            for link in self.links:
                link.update_position()
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.temp_line = QGraphicsLineItem(QLineF(self.scenePos(), event.scenePos()))
            pen = QPen(Qt.GlobalColor.gray, 2, Qt.PenStyle.DashLine)
            self.temp_line.setPen(pen)
            self.scene().addItem(self.temp_line)
            event.accept()
        elif event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = True
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.temp_line:
            self.temp_line.setLine(QLineF(self.scenePos(), event.scenePos()))
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.temp_line:
            self.scene().removeItem(self.temp_line)
            self.temp_line = None
            for item in self.scene().items(event.scenePos()):
                if isinstance(item, Node) and item != self:
                    self.create_link_callback(self, item)
                    break
            event.accept()
        else:
            super().mouseReleaseEvent(event)
            if event.button() == Qt.MouseButton.LeftButton and self.is_dragging:
                self.is_dragging = False

class Link(QGraphicsLineItem):
    def __init__(self, source, target):
        super().__init__()
        self.source = source
        self.target = target
        self.source.add_link(self)
        self.target.add_link(self)
        self.setPen(QPen(Qt.GlobalColor.red, 2))
        self.setFlag(QGraphicsLineItem.GraphicsItemFlag.ItemIsSelectable)
        self.setZValue(-1)
        self.update_position()

    def update_position(self):
        self.setLine(QLineF(self.source.pos(), self.target.pos()))