# Festo MPS 颜色管理系统

## 🎨 概述

本次更新为Festo MPS Distribution Station添加了完整的多颜色工件管理功能，支持黑色、红色、银色三种工件的智能分配和追踪。

## ✨ 新增功能

### 1. 多颜色工件支持
- **三种标准颜色**: 黑色 (black)、红色 (red)、银色 (silver)
- **灵活配置**: 支持任意数量颜色的扩展
- **智能选择**: 按照先进先出原则自动选择下一个工件颜色

### 2. 智能补料系统
- **自动平衡分配**: 默认补料时自动平衡各颜色工件数量
- **自定义配比**: 支持用户指定各颜色工件的精确数量
- **实时验证**: 补料时自动验证总数量和颜色分配的合理性

### 3. 增强的用户界面
- **颜色状态显示**: 实时显示各颜色工件的库存情况
- **当前工件追踪**: 显示正在处理的工件颜色
- **自定义补料面板**: 提供直观的颜色配比设置界面

### 4. 详细的日志记录
- **颜色信息集成**: 所有日志输出都包含当前颜色分布信息
- **工件追踪**: 记录每个弹出工件的具体颜色
- **操作历史**: 完整记录补料和颜色变更操作

## 🚀 使用方法

### 启动系统
```bash
python festo.py
```

### 基本操作

#### 1. 查看当前状态
- 在控制面板的"Status"区域查看：
  - `Current Workpieces`: 总工件数
  - `Color Distribution`: 各颜色工件分布 (格式: black:3 | red:2 | silver:1)
  - `Current Color Workpiece`: 当前处理的工件颜色

#### 2. 颜色配比补料 (简化界面)
1. 确保料仓为空 (系统会自动检查)
2. 在"Color Distribution"区域设置各颜色数量：
   - **Black**: 设置黑色工件数量 (默认: 3)
   - **Red**: 设置红色工件数量 (默认: 3)
   - **Silver**: 设置银色工件数量 (默认: 2)
3. 点击右侧的"Manual Refill"按钮
4. 系统按指定配比补料

**界面布局**: `Black: [3] Red: [3] Silver: [2] [Manual Refill]` (按钮与Exit对齐)

### 编程接口

#### 基本颜色管理
```python
# 获取下一个工件颜色
next_color = station.get_next_workpiece_color()

# 弹出工件 (自动选择颜色)
if station.eject_workpiece():
    current_color = station.current_workpiece_color
    print(f"弹出工件颜色: {current_color}")

# 获取颜色分布摘要
color_summary = station.get_color_summary()
print(f"当前分布: {color_summary}")
```

#### 补料操作
```python
# 颜色配比补料 (推荐方式)
color_distribution = {'black': 3, 'red': 3, 'silver': 2}
station.manual_refill(8, color_distribution)

# 自定义配比示例
color_distribution = {'black': 5, 'red': 2, 'silver': 1}
station.manual_refill(8, color_distribution)

# 自动平衡补料 (仍然支持，但界面不再使用)
station.manual_refill(8)  # 自动平衡分配
```

#### 颜色配置扩展
```python
# 添加新颜色
station.available_colors.append('blue')
station.workpiece_colors['blue'] = 0

# 使用新颜色
new_distribution = {'black': 2, 'red': 2, 'blue': 4}
station.manual_refill(8, new_distribution)
```

## 🔧 技术实现

### 核心数据结构
```python
# 颜色管理属性
self.available_colors = ['black', 'red', 'silver']
self.workpiece_colors = {
    'black': 3,   # 各颜色工件数量
    'red': 3,
    'silver': 2
}
self.current_workpiece_color = None  # 当前处理工件颜色
```

### 关键方法
- `get_next_workpiece_color()`: 获取下一个可用工件颜色
- `eject_workpiece()`: 弹出工件并更新颜色库存
- `get_color_summary()`: 生成颜色分布摘要字符串
- `_distribute_colors_evenly()`: 自动平衡颜色分配
- `_set_color_distribution()`: 设置自定义颜色分配

## 🧪 测试验证

运行测试脚本验证功能：
```bash
python test_color_management.py
```

测试覆盖：
- ✅ 初始颜色分布
- ✅ 工件弹出和颜色选择
- ✅ 自动平衡补料
- ✅ 自定义颜色配比补料
- ✅ 边界条件处理
- ✅ 颜色配置扩展性
- ✅ Testing Station集成演示

## 🔮 后续扩展

### Testing Station 集成
```python
class TestingStation(BaseStation):
    def detect_color(self, workpiece):
        """颜色检测逻辑"""
        # 实现颜色检测算法
        pass

    def quality_assessment_by_color(self, color):
        """基于颜色的质量标准"""
        color_standards = {
            'black': {'tolerance': 0.1, 'pass_rate': 0.95},
            'red': {'tolerance': 0.05, 'pass_rate': 0.90},
            'silver': {'tolerance': 0.02, 'pass_rate': 0.98}
        }
        return color_standards.get(color, color_standards['black'])
```

### Processing Station 差异化处理
```python
class ProcessingStation(BaseStation):
    def get_processing_parameters(self, color):
        """根据颜色获取加工参数"""
        parameters = {
            'black': {'drill_speed': 1000, 'feed_rate': 100},
            'red': {'drill_speed': 800, 'feed_rate': 80},    # 特殊处理
            'silver': {'drill_speed': 1200, 'feed_rate': 120} # 高精度
        }
        return parameters.get(color, parameters['black'])
```

## 🔧 问题修复 (v1.1.3)

### **修复的问题**:
1. **重复补料**: 添加 `refill_in_progress` 标志防止多次补料操作
2. **时机错误**: 确保只在料仓空**且系统空闲**时才能进行补料
3. **多线程冲突**: 使用 `pending_refill_timer` 管理定时器，避免冲突
4. **颜色分布异常**: 修复补料完成后颜色分布更新逻辑
5. **时间显示**: 仿真时间显示为整数，保持内部计算精度
6. **状态检查**: 添加系统状态检查，防止运行时补料
7. **State 6补料**: 允许在最后工件弹出后(State 6)进行补料

### **补料允许条件** (严格检查):
补料操作只有在**所有条件同时满足**时才被允许：

1. **料仓必须为空**: `S3 = False` (工件数量 = 0)
2. **系统状态必须是以下之一**:
   - `State = 0` (系统空闲状态)
   - `State = 6 且 S3 = False` (最后工件弹出后)
3. **无补料进行**: `refill_in_progress = False` (没有其他补料操作)

**应用场景**:
- **系统启动前**: State 0 + 料仓空
- **最后工件弹出后**: State 6 + 料仓空 (真实工业场景)

**错误提示**:
- 料仓非空: "Manual refill is only available when magazine is empty"
- 状态错误: "Manual refill only available when system is idle (State 0) or after last workpiece ejected (State 6 with empty magazine)"
- 补料进行: "Refill already in progress, please wait"

### **补料时间说明**:
- **操作员响应时间**: 从料仓空到点击Manual Refill的时间
- **物理补料时间**: 工件数量 × 2秒/件 (模拟真实补料过程)
- **总补料时间**: 响应时间 + 物理时间

## 📊 性能影响

- **内存开销**: 增加约 < 1KB (颜色数据结构)
- **计算复杂度**: O(n) 其中 n 为颜色种类数 (通常 ≤ 5)
- **界面响应**: 无明显影响
- **日志大小**: 每条日志增加约 20-30 字符
- **补料保护**: 防止重复操作，提高系统稳定性

## 🎯 应用价值

1. **教学演示**: 更真实地模拟工业生产中的多品种管理
2. **算法验证**: 为颜色检测、分拣算法提供测试平台
3. **流程优化**: 研究不同颜色配比对生产效率的影响
4. **质量控制**: 模拟基于颜色的差异化质量标准

---

**更新日期**: 2025年5月
**版本**: v1.1.0 (颜色管理增强版)
**兼容性**: 完全向后兼容，现有功能不受影响
