import json
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any
from pathlib import Path

# 确保能加载 src 里的模块
import sys
sys.path.append(str(Path(__file__).parent.parent))
from src.aligner import AlignmentResult

# ============================================================================
# 数据结构：关键帧与动画元素
# ============================================================================

@dataclass
class Keyframe:
    time: float          # 绝对时间 (秒)
    x: Optional[float] = None
    y: Optional[float] = None
    scale: Optional[float] = None  # 1.0 = 100%
    alpha: Optional[float] = None  # 1.0 = 不透明, 0.0 = 透明
    blur: Optional[float] = None
    color: Optional[str] = None    # Hex 颜色 (例如 "#FFFFFF")
    ease: str = "easeOutCubic"     # 缓动曲线

@dataclass
class Element:
    id: str
    text: str
    type: str            # "line" 或 "word"
    keyframes: List[Keyframe]

# ============================================================================
# 导演类：根据不同风格的“剧本”排版关键帧
# ============================================================================

class Choreographer:
    def __init__(self, screen_width=1920, screen_height=1080):
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.elements: Dict[str, Element] = {}
        
    def _get_element(self, el_id: str, text: str, el_type: str) -> Element:
        if el_id not in self.elements:
            self.elements[el_id] = Element(id=el_id, text=text, type=el_type, keyframes=[])
        return self.elements[el_id]

    def add_keyframe(self, el_id: str, text: str, el_type: str, kf: Keyframe):
        el = self._get_element(el_id, text, el_type)
        el.keyframes.append(kf)

    def export_json(self, output_path: str):
        # 排序关键帧
        for el in self.elements.values():
            el.keyframes.sort(key=lambda k: k.time)
            
        data = {
            "version": "1.0",
            "meta": {
                "resolution": [self.screen_width, self.screen_height],
                "fps": 60
            },
            "elements": [asdict(el) for el in self.elements.values()]
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✅ 自动化关键帧 JSON 已导出至: {output_path}")

    # ------------------------------------------------------------------------
    # 剧本 1：复刻 Apple Music 风格逻辑
    # ------------------------------------------------------------------------
    def script_apple_music(self, alignment: AlignmentResult):
        lines = alignment.lines
        N = len(lines)
        if N == 0: return
        
        # 基础排版参数
        line_height = 80
        center_y = self.screen_height * 0.35  # 焦点行在屏幕偏上方
        center_x = self.screen_width / 2.0
        
        # 定义距离函数，计算任意行 j 在焦点 k 时的状态
        def get_state(j: int, k: int) -> dict:
            d = abs(j - k)
            y = center_y + (j - k) * line_height
            scale = max(0.7, 1.0 - d * 0.05) if d > 0 else 1.0
            blur = d * 3.0
            
            # 透明度和颜色
            if j == k:
                alpha = 1.0
                color = "#FFFFFF" # 焦点行纯白
            else:
                alpha = max(0.0, 0.6 - d * 0.15)
                color = "#CCCCCC" # 上下文偏灰
                
            return {"y": y, "scale": scale, "blur": blur, "alpha": alpha, "color": color}

        # 遍历每一行，为它的一生（出场 -> 激活 -> 退场）打关键帧
        for j, line in enumerate(lines):
            line_id = f"line_{j}"
            
            # 只有当焦点 k 走到 j 附近时，这行才可见
            for k in range(max(0, j - 4), min(N, j + 5)):
                # 焦点 k 的激活时间段：从 lines[k].start 开始
                slot_start = lines[k].start
                
                # 定义 0.5s 的过渡动画期
                trans_dur = 0.5
                t_anim_start = slot_start - trans_dur
                t_anim_end = slot_start
                
                # 计算目标状态
                state = get_state(j, k)
                
                # 写入关键帧：在过渡期结束时达到该状态
                # (引擎在渲染时会自动在 t_anim_start 和 t_anim_end 之间做线性或曲线插值)
                self.add_keyframe(line_id, line.text, "line", Keyframe(
                    time=t_anim_end,
                    x=center_x,
                    y=state["y"],
                    scale=state["scale"],
                    blur=state["blur"],
                    alpha=state["alpha"],
                    color=state["color"],
                    ease="easeOutCubic"
                ))

            # 卡拉OK 逐字点亮关键帧 (挂载在 Word 元素上)
            for i, word in enumerate(line.words):
                word_id = f"word_{j}_{i}"
                
                # 没唱到的时候是半透明
                self.add_keyframe(word_id, word.word, "word", Keyframe(
                    time=line.start - 0.1, alpha=0.5, color="#CCCCCC", scale=1.0
                ))
                
                # 唱到的瞬间：瞬间变白，微微放大 (动次打次的弹性)
                self.add_keyframe(word_id, word.word, "word", Keyframe(
                    time=word.start, alpha=1.0, color="#FFFFFF", scale=1.1, ease="spring"
                ))
                
                # 唱完后：缩放恢复正常
                self.add_keyframe(word_id, word.word, "word", Keyframe(
                    time=word.end, scale=1.0, ease="easeOutQuad"
                ))

if __name__ == "__main__":
    # 测试代码：读取对齐 JSON 并生成 Choreography JSON
    alignment_path = Path("./output/匠心入梦01_alignment.json")
    output_json = Path("./output/匠心入梦01_choreography.json")
    
    if alignment_path.exists():
        alignment = AlignmentResult.load_json(alignment_path)
        director = Choreographer()
        director.script_apple_music(alignment)
        director.export_json(str(output_json))
    else:
        print(f"未找到测试文件: {alignment_path}")
