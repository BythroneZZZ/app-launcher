// background.qml — GPU 加速背景层（替代 paintEvent 的 CPU 绘制）
// 由 BackgroundLayer(QQuickWidget) 加载；噪点纹理由 Python 导出后注入
import QtQuick

Rectangle {
    id: root
    color: "#0b0e14"
    property string glowColor: ""              // Python rootObject().setProperty() 更新
    property int glowAnimMs: 400               // 减少动画时由 Python 设为 0

    // 对角渐变（替代 CPU 线性渐变叠加）
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            orientation: Gradient.Vertical
            GradientStop { position: 0.0; color: "#101626" }
            GradientStop { position: 1.0; color: "#0a0d14" }
        }
    }

    // 噪点纹理（Python 导出的 PNG，平铺 + 50% 透明度）
    Image {
        id: noise
        anchors.fill: parent
        source: noisePath                          // Python 注入的文件路径
        fillMode: Image.Tile
        opacity: 0.5
        visible: noisePath !== ""
    }

    // 四角暗角（上下两段渐变近似径向暗角）
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            orientation: Gradient.Vertical
            GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, 0) }
            GradientStop { position: 0.6; color: Qt.rgba(0, 0, 0, 0) }
            GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.18) }
        }
    }

    // 底部辉光（主色，Python 通过 setGlowColor 注入）
    Rectangle {
        id: glowRect
        anchors.fill: parent
        color: "transparent"
        visible: root.glowColor !== ""
        Rectangle {
            anchors.bottom: parent.bottom
            anchors.horizontalCenter: parent.horizontalCenter
            width: parent.width
            height: parent.height * 0.5
            gradient: Gradient {
                orientation: Gradient.Vertical
                GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, 0) }
                GradientStop {
                    position: 1.0
                    color: root.glowColor
                    Behavior on color { ColorAnimation { duration: root.glowAnimMs } }
                }
            }
        }
    }
}
