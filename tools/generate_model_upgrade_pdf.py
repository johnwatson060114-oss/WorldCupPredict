from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "artifacts"
OUT_PATH = OUT_DIR / "WorldCupPredict_模型升级实施方案_V2.pdf"

BLUE = colors.HexColor("#174A67")
TEAL = colors.HexColor("#167C80")
GREEN = colors.HexColor("#287A4B")
RED = colors.HexColor("#B33A3A")
YELLOW = colors.HexColor("#FFF3BF")
INK = colors.HexColor("#24313A")
MUTED = colors.HexColor("#61717C")
LIGHT = colors.HexColor("#E8F0F3")
PALE_BLUE = colors.HexColor("#EEF6FA")
PALE_GREEN = colors.HexColor("#EFF8F1")
PALE_RED = colors.HexColor("#FFF1F0")


def register_fonts() -> None:
    pdfmetrics.registerFont(TTFont("CJK", r"C:\Windows\Fonts\msyh.ttc", subfontIndex=0))
    pdfmetrics.registerFont(TTFont("CJK-Bold", r"C:\Windows\Fonts\msyhbd.ttc", subfontIndex=0))


def styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontName="CJK-Bold", fontSize=22,
            leading=31, textColor=BLUE, alignment=TA_CENTER, spaceAfter=8 * mm,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["Normal"], fontName="CJK", fontSize=10.5,
            leading=17, textColor=MUTED, alignment=TA_CENTER, spaceAfter=5 * mm,
        ),
        "h1": ParagraphStyle(
            "h1", parent=base["Heading1"], fontName="CJK-Bold", fontSize=15,
            leading=22, textColor=BLUE, spaceBefore=4 * mm, spaceAfter=3 * mm,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontName="CJK-Bold", fontSize=12,
            leading=18, textColor=TEAL, spaceBefore=3 * mm, spaceAfter=2 * mm,
        ),
        "body": ParagraphStyle(
            "body", parent=base["BodyText"], fontName="CJK", fontSize=10.3,
            leading=17, textColor=INK, alignment=TA_LEFT, spaceAfter=2.2 * mm,
        ),
        "bullet": ParagraphStyle(
            "bullet", parent=base["BodyText"], fontName="CJK", fontSize=10.1,
            leading=16.5, textColor=INK, leftIndent=5 * mm, firstLineIndent=-3.5 * mm,
            bulletIndent=1.5 * mm, spaceAfter=1.3 * mm,
        ),
        "small": ParagraphStyle(
            "small", parent=base["BodyText"], fontName="CJK", fontSize=8.8,
            leading=14, textColor=MUTED,
        ),
        "formula": ParagraphStyle(
            "formula", parent=base["BodyText"], fontName="CJK", fontSize=12,
            leading=20, textColor=BLUE, alignment=TA_CENTER, spaceBefore=2 * mm,
            spaceAfter=3 * mm,
        ),
        "callout": ParagraphStyle(
            "callout", parent=base["BodyText"], fontName="CJK-Bold", fontSize=10.3,
            leading=17, textColor=BLUE, spaceAfter=0,
        ),
        "table": ParagraphStyle(
            "table", parent=base["BodyText"], fontName="CJK", fontSize=8.6,
            leading=13, textColor=INK,
        ),
        "table_head": ParagraphStyle(
            "table_head", parent=base["BodyText"], fontName="CJK-Bold", fontSize=8.8,
            leading=13, textColor=colors.white, alignment=TA_CENTER,
        ),
    }


def P(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def bullet(text: str, s: dict[str, ParagraphStyle]) -> Paragraph:
    return P(f"• {text}", s["bullet"])


def callout(text: str, s: dict[str, ParagraphStyle], color=PALE_BLUE) -> Table:
    table = Table([[P(text, s["callout"])]], colWidths=[166 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color),
        ("BOX", (0, 0), (-1, -1), 0.7, BLUE),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
    ]))
    return table


def make_table(rows: list[list[str]], widths: list[float], s: dict[str, ParagraphStyle]) -> Table:
    cooked = []
    for ridx, row in enumerate(rows):
        style = s["table_head"] if ridx == 0 else s["table"]
        cooked.append([P(cell, style) for cell in row])
    table = Table(cooked, colWidths=[w * mm for w in widths], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLUE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#B8C8D0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7FAFB")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.3 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
    ]))
    return table


def footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setStrokeColor(LIGHT)
    canvas.line(20 * mm, 14 * mm, 190 * mm, 14 * mm)
    canvas.setFont("CJK", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(20 * mm, 9 * mm, "WorldCupPredict 模型升级实施方案 V2")
    canvas.drawRightString(190 * mm, 9 * mm, f"第 {doc.page} 页")
    canvas.restoreState()


def build_story(s: dict[str, ParagraphStyle]):
    story = []
    story += [
        Spacer(1, 18 * mm),
        P("WorldCupPredict", s["title"]),
        P("模型升级实施方案 V2", s["title"]),
        P("历史标定 · 纪律状态 · 100,000 条连续赛事路径 · 赛前情报 · 严格回测", s["subtitle"]),
        Spacer(1, 5 * mm),
        callout(
            "核心目标：把当前固定参数的单场比分模型，升级为可复现、可回测、能够追踪球员黄牌与停赛状态的连续赛事概率系统。",
            s,
            PALE_GREEN,
        ),
        Spacer(1, 9 * mm),
        P("设计原则", s["h1"]),
        bullet("100,000 次必须是真实执行的联合模拟，不删除现有描述。", s),
        bullet("模拟次数只减少抽样误差，不能修复错误的数据、参数或结构。", s),
        bullet("确定发生的停赛立即进入阵容模型；球员因怕停赛而改变行为，必须先回测。", s),
        bullet("新增因素只有在严格样本外验证中稳定缩小误差，才进入正式概率。", s),
        bullet("大模型负责读取与结构化证据，本地统计程序负责概率、模拟和资金结算。", s),
        Spacer(1, 10 * mm),
        P("版本定位", s["h2"]),
        P("本文件是实施规范，不代表所有能力已经完成。开发时应保留旧模型作为基线，每完成一个阶段就进行可复现验证。", s["body"]),
        PageBreak(),
    ]

    story += [
        P("一、需要解决的核心问题", s["h1"]),
        make_table([
            ["当前问题", "可能造成的误差", "处理方式"],
            ["页面显示 100,000 次联合模拟，但比分由固定公式直接计算", "用户误以为参数不确定性已经传播", "实现真实的 100,000 条参数与比赛路径"],
            ["资金模拟实际为 30,000 次", "与页面口径不一致", "统一为 100,000 条同源路径"],
            ["总进球、低比分修正和近期权重为启发式常数", "形成稳定但系统性偏差", "使用历史比赛和滚动回测标定"],
            ["串关每一腿由总概率开方近似", "破坏真实概率与玩法相关性", "使用同一模拟比分逐腿结算"],
            ["纪律状态未进入连续赛事模型", "遗漏停赛、轮换和公平竞赛排名影响", "增加规则引擎和球员状态机"],
        ], [45, 57, 64], s),
        Spacer(1, 5 * mm),
        callout("先冻结当前模型、预测输出和测试结果。新模型只有在样本外指标稳定改善后，才能替换基线。", s, YELLOW),
        P("二、历史数据与时间一致性", s["h1"]),
        bullet("收集最近约 6–8 年的成年男子国家队比赛，但窗口长度由回测确定。", s),
        bullet("只使用 90 分钟结果；加时赛与点球大战单独记录。", s),
        bullet("保存赛事类型、阶段、场地属性、东道主、中立场、赛前 Elo、赔率、阵容、事件和规则时期。", s),
        bullet("所有特征必须带发布时间；预测过去比赛时，只能读取当时已经公开的信息。", s),
        bullet("保存原始快照和数据哈希，避免数据源后来修订导致不可复现。", s),
        P("友谊赛处理", s["h2"]),
        P("友谊赛是专业国家队比赛，但轮换、实验和求胜动机更不稳定。它对比赛较少的球队仍有信息价值，因此默认保留、单独标记并降权，同时增加不确定性。最终应比较“排除”“固定降权”“自动学习权重”三种方案。", s["body"]),
        PageBreak(),
    ]

    story += [
        P("三、基础进球模型重新标定", s["h1"]),
        P("候选模型不应预先指定唯一赢家，而应在相同数据切分下公平比较。", s["body"]),
        make_table([
            ["候选模型", "适用目的", "主要风险"],
            ["时间衰减 Dixon–Coles", "解释低比分相关性，计算成本低", "高比分尾部和过度离散处理有限"],
            ["双变量泊松", "显式描述双方进球相关性", "参数更多，样本不足时不稳定"],
            ["负二项或混合模型", "处理进球方差高于泊松均值", "容易增加复杂度和过拟合"],
            ["动态层级攻防模型", "弱队和低样本球队可向整体均值收缩", "训练与不确定性估计更复杂"],
        ], [42, 63, 61], s),
        P("Elo 的正确角色", s["h2"]),
        P("Elo可作为球队实力先验或协变量，但不能与近期比分、球队攻防强度和市场赔率无条件叠加，否则同一实力信息可能被重复计算。", s["body"]),
        P("概率评估", s["h2"]),
        bullet("主要指标：Log Loss、RPS、Brier Score、可靠性图与校准误差。", s),
        bullet("使用嵌套式滚动时间回测选择参数，防止在验证集上反复调参。", s),
        bullet("ROI只作为次要指标；短期ROI受赔率和偶然赛果影响很大。", s),
        bullet("保留统计概率、市场去水概率和回测学习的组合概率三套结果。", s),
        P("市场概率组合", s["formula"]),
        P("P<sub>blend</sub> = αP<sub>stat</sub> + (1 − α)P<sub>market</sub>", s["formula"]),
        P("其中组合权重 α 必须由过去时点的样本外回测学习，不能人工指定。", s["body"]),
        PageBreak(),
    ]

    story += [
        P("四、黄牌、停赛与规则状态机", s["h1"]),
        callout("纪律规则属于确定性业务逻辑；球员行为变化属于统计假设。两者必须分开实现。", s, PALE_RED),
        P("纪律规则引擎", s["h2"]),
        P("规则引擎应根据 FIFA 最终发布并适用于 2026 世界杯的竞赛规程配置累计窗口、清零节点、自动停赛和追加处罚。不要把当前理解硬编码为不可修改常数。", s["body"]),
        make_table([
            ["球员状态字段", "用途"],
            ["球员唯一ID、球队、位置", "避免同名球员和队伍映射错误"],
            ["当前累计窗口与黄牌数", "判断下一张黄牌是否触发停赛"],
            ["本场黄牌、第二黄牌和直接红牌", "处理本场罚下及后续停赛"],
            ["待执行停赛场数", "生成下一场可用阵容"],
            ["规则版本和官方决定时间", "处理清零、撤销、申诉和追加处罚"],
        ], [65, 101], s),
        P("比赛结束后的更新顺序", s["h2"]),
        bullet("处理本场第二黄牌和直接红牌。", s),
        bullet("处理跨比赛累计达到停赛阈值。", s),
        bullet("生成下一场停赛名单，并保留已经触发的处罚。", s),
        bullet("到达官方清零节点时，只清除规则允许清除的未触发累计。", s),
        bullet("随后处理官方撤销、身份纠正、申诉和追加处罚。", s),
        P("黄牌的三条影响路径", s["h2"]),
        bullet("本场：已吃牌球员可能降低对抗、提高被换下概率，并承担第二黄牌罚下风险。", s),
        bullet("下一场：累计触发停赛后，由替代球员改变阵容强度。", s),
        bullet("整届赛事：纪律分可能影响小组排名，停赛会改变后续晋级路径。", s),
        PageBreak(),
    ]

    story += [
        P("五、黄牌行为模型如何避免新增误差", s["h1"]),
        P("不能直接假设“带牌球员一定踢得保守”或“防守能力固定下降”。比赛阶段、比分、位置、替补深度和教练选择都会改变方向。", s["body"]),
        make_table([
            ["因素", "可能影响", "默认处理"],
            ["赛前已有累计黄牌", "轮换、谨慎对抗、提前换下", "先展示并扩大区间；回测后才改均值"],
            ["本场已经吃牌", "二黄风险、逼抢下降、被针对", "事件发生后切换状态，不从开场固定调整"],
            ["裁判尺度", "牌数、点球、红牌和比赛连续性", "层级收缩；样本不足时回归平均"],
            ["球队和球员犯规风格", "个人吃牌概率", "控制对手、赛事和位置后估计"],
            ["晋级形势", "是否保护核心球员", "只使用赛前可见且可编码的状态"],
        ], [40, 61, 65], s),
        P("球员缺阵价值", s["h2"]),
        P("停赛影响取决于预计首发与替代球员的差值，而不是统一扣减固定 xG。", s["body"]),
        P("ΔV<sub>absence</sub> = V<sub>starter</sub> − V<sub>replacement</sub>", s["formula"]),
        bullet("分别估计门将、中卫、防守型中场、组织核心和前锋。", s),
        bullet("考虑替补深度、阵型适配和同位置替代，而不是只看球员名气。", s),
        bullet("低样本球员向位置、球队和赛事平均值收缩。", s),
        P("新增因素准入", s["h2"]),
        bullet("每次只加入一个因素，进行消融测试。", s),
        bullet("多个滚动窗口中稳定改善，且概率校准不恶化。", s),
        bullet("使用分块 bootstrap 检查改善方向是否稳定。", s),
        bullet("若只在少数红牌或极端比赛上改善，则不进入正式模型。", s),
        PageBreak(),
    ]

    story += [
        P("六、真正的 100,000 条连续赛事路径", s["h1"]),
        P("每条路径应模拟整套共享状态，而不是固定 xG 后重复抽取比分。", s["body"]),
        make_table([
            ["步骤", "每条路径执行内容"],
            ["1", "联合抽取模型参数，保留参数之间的协方差"],
            ["2", "抽取球队潜在攻防强度、阵容可用性和比赛环境"],
            ["3", "生成进球、黄牌、红牌、换人及其发生时间"],
            ["4", "事件发生后更新比赛状态和剩余时间进球强度"],
            ["5", "由同一个最终比分结算胜平负、让球、比分和总进球"],
            ["6", "更新积分、净胜球、纪律分、黄牌累计和停赛状态"],
            ["7", "按照官方规则执行晋级、排名和清零节点"],
            ["8", "用更新后的阵容继续模拟下一场，直到淘汰或决赛结束"],
        ], [18, 148], s),
        P("参数不确定性的来源", s["h2"]),
        bullet("模型估计协方差或层级模型后验样本。", s),
        bullet("保持时间和赛事结构的分块 bootstrap。", s),
        bullet("阵容未确认时的候选首发概率。", s),
        bullet("规则、天气和裁判因素只在通过回测后进入均值。", s),
        callout("禁止为每个参数随意指定一个正态误差。错误的误差分布会让十万次模拟看起来精细，实际却引入新的模型偏差。", s, PALE_RED),
        P("模拟质量记录", s["h2"]),
        bullet("固定随机种子，保存实际完成的路径数。", s),
        bullet("输出Monte Carlo标准误差、概率区间和稳定度。", s),
        bullet("增加抽样收敛检查：25,000、50,000和100,000次结果应逐步稳定。", s),
        PageBreak(),
    ]

    story += [
        P("七、资金模拟必须与比赛路径一致", s["h1"]),
        bullet("同一场比赛的所有玩法共享同一个模拟比分。", s),
        bullet("删除串关总概率开方近似，按每条路径逐腿判断。", s),
        bullet("不同比赛暂时可条件独立，但应记录该假设；同组形势和轮换可能产生关联。", s),
        bullet("使用同一批100,000条赛事路径结算单关、串关和滚动本金。", s),
        bullet("输出期望本金、中位数、5%与95%分位、盈利概率、停止概率和最大回撤。", s),
        bullet("用模拟分位数替代当前人工概率下界。", s),
        bullet("下注门槛考虑“期望收益为正的后验概率”，继续使用分数凯利和严格上限。", s),
        P("八、大模型赛前情报层", s["h1"]),
        P("大模型适合读取官方伤停、首发、纪律公告、教练发布会、战术报道、裁判任命和规则更新，但不能自由决定概率修正。", s["body"]),
        make_table([
            ["必须输出的字段", "说明"],
            ["事件类型与涉及对象", "伤停、停赛、预计轮换、战术变化等"],
            ["原始来源与发布时间", "确保早于预测截止时间"],
            ["确认等级", "官方确认、可靠报道或未经证实传闻"],
            ["置信度与冲突信息", "保留不确定性，不强行合并"],
            ["结构化结论", "供本地程序读取，但影响系数来自回测"],
        ], [58, 108], s),
        callout("没有历史赛前快照，就无法可靠回测新闻和战术因素。从系统上线之日起，应每日保存不可变的情报快照。", s, YELLOW),
        PageBreak(),
    ]

    story += [
        P("九、误差来源与控制", s["h1"]),
        make_table([
            ["风险", "为什么会发生", "控制措施"],
            ["数据泄漏", "使用赛后修订数据、最终首发或收盘赔率预测过去", "保存时间戳快照；按预测截止时间读取"],
            ["重复计权", "Elo、近期战绩、市场赔率表达相同实力", "明确变量角色；消融测试；正则化"],
            ["过拟合", "因素多、世界杯样本少", "层级收缩、嵌套滚动回测、简化优先"],
            ["分布漂移", "规则、VAR、补时和赛事环境改变", "设置规则时期；近期窗口加权；监控校准"],
            ["纪律混杂", "强对抗比赛同时导致更多牌与更多进球", "控制球队、对手、赛事、比分和时间状态"],
            ["虚假精度", "十万次使小数稳定但输入假设错误", "展示参数区间、模型版本和校准表现"],
            ["球员样本稀疏", "个人国家队出场少", "向位置、球队和总体均值收缩"],
        ], [35, 65, 66], s),
        P("十、最终实施顺序", s["h1"]),
        make_table([
            ["阶段", "工作", "验收条件"],
            ["1", "冻结旧模型与输出，补充版本和数据快照", "旧结果可重复生成"],
            ["2", "建立无时间泄漏的历史比赛、球员和事件库", "每个字段可追溯到赛前来源"],
            ["3", "实现可配置的FIFA纪律规则引擎", "黄牌累计、清零、停赛测试通过"],
            ["4", "重新拟合并选择基础进球模型", "样本外指标优于旧基线"],
            ["5", "实现真实100,000条联合路径", "固定种子可复现且通过收敛检查"],
            ["6", "重写同路径资金模拟", "所有玩法由共享比分正确结算"],
            ["7", "加入确定停赛和替补价值", "阵容变化可解释、可追踪"],
            ["8", "逐项测试黄牌行为、裁判、规则、天气等因素", "消融回测稳定改善才启用"],
            ["9", "接入大模型结构化情报层", "来源、时间、置信度和冲突均可审计"],
            ["10", "更新界面与持续监控", "概率校准、数据覆盖和模型漂移可见"],
        ], [16, 92, 58], s),
        Spacer(1, 5 * mm),
        callout(
            "最终原则：确定事实立即处理；不确定假设先进入回测。模型复杂度只有在稳定缩小样本外误差时才有价值。",
            s,
            PALE_GREEN,
        ),
        PageBreak(),
    ]

    story += [
        P("十一、上线验收清单", s["h1"]),
        bullet("每场比赛确实完成100,000条有效路径，且输出实际计数。", s),
        bullet("固定种子、数据快照和模型版本能够复现结果。", s),
        bullet("比分矩阵、胜平负和各玩法概率满足归一化检查。", s),
        bullet("同场所有投注由同一模拟比分结算。", s),
        bullet("黄牌累计、清零、二黄、直红、停赛和申诉均有规则测试。", s),
        bullet("小组排名执行完整官方规则，包括适用时的纪律分。", s),
        bullet("新模型在严格样本外回测中优于旧模型，且校准不恶化。", s),
        bullet("未回测因素只展示或扩大区间，不直接修改均值。", s),
        bullet("Python测试、前端测试、生产构建和PDF/页面文案核对全部通过。", s),
        P("建议的正式输出层次", s["h2"]),
        make_table([
            ["输出", "用途"],
            ["基础统计概率", "显示不含市场和新闻的独立模型判断"],
            ["市场去水概率", "作为强基准和价值比较对象"],
            ["组合概率", "仅使用样本外学习的权重"],
            ["100,000次模拟概率与区间", "传播参数、阵容和赛事路径不确定性"],
            ["启用因素与证据", "让用户知道哪些信息真正改变了概率"],
            ["停赛与黄牌风险", "区分确定缺阵、本场二黄风险和未来累计风险"],
        ], [60, 106], s),
        Spacer(1, 8 * mm),
        P("结论", s["h1"]),
        P("这次优化的重点不是简单增加更多变量，而是建立一套有顺序、有状态、有证据和有回测门槛的预测系统。黄牌累计提醒我们：世界杯不是一组彼此独立的比赛。真正合理的模拟必须让球员状态、停赛、阵容、排名和后续对手沿着同一条赛事路径持续演化。", s["body"]),
        callout("复杂度不是目标，可验证的误差缩小才是目标。", s, YELLOW),
    ]
    return story


def main() -> None:
    register_fonts()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    s = styles()
    doc = SimpleDocTemplate(
        str(OUT_PATH),
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=20 * mm,
        title="WorldCupPredict 模型升级实施方案 V2",
        author="OpenAI Codex",
        subject="世界杯预测模型、纪律规则与100,000次联合模拟实施方案",
    )
    doc.build(build_story(s), onFirstPage=footer, onLaterPages=footer)
    print(OUT_PATH)


if __name__ == "__main__":
    main()
