import streamlit as st
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import pandas as pd
import time


# ==============================================================================
# 🧠 Logic Kernel (V45 - 全功能回归版)
# ==============================================================================

# -------------------------------
# 1. 状态初始化
# -------------------------------
def init_app_state():
    if "main_round" not in st.session_state:
        st.session_state["main_round"] = 0
    if "gang_rows" not in st.session_state:
        st.session_state["gang_rows"] = 1
    if "ledger_data" not in st.session_state:
        st.session_state["ledger_data"] = []
    if "p_names" not in st.session_state:
        st.session_state.p_names = ["玩家A", "玩家B", "玩家C", "玩家D"]


def next_round():
    """进入下一局"""
    st.session_state["main_round"] += 1
    st.session_state["gang_rows"] = 1
    st.rerun()


# -------------------------------
# 2. 基础工具函数
# -------------------------------
def parse_card(card_str: str) -> Optional[Tuple[int, str]]:
    if not card_str: return None
    try:
        suit = card_str[-1];
        num = int(card_str[:-1])
        if suit not in ["筒", "条", "万"] or num < 1 or num > 9: return None
        return num, suit
    except:
        return None


def get_fan_multipliers(fan_card: str) -> Tuple[int, int]:
    parsed = parse_card(fan_card)
    if not parsed: return 1, 1
    num, suit = parsed
    if num == 9 and suit == "条": return 2, 1
    if num == 7 and suit == "筒": return 1, 2
    return 1, 1


@dataclass
class Transaction:
    payer: str;
    receiver: str;
    amount: int;
    reason: str;
    category: str

    def reverse(self):
        return Transaction(self.receiver, self.payer, self.amount, f"未听牌包赔-{self.reason}", self.category)


def build_common_chicken_cfg(base_yj, mul_yj, base_b8, mul_b8, fan_card):
    f_yj, f_b8 = get_fan_multipliers(fan_card)
    return {"幺鸡": int(base_yj) * int(mul_yj) * int(f_yj), "八筒": int(base_b8) * int(mul_b8) * int(f_b8)}


# -------------------------------
# 3. 校验逻辑
# -------------------------------
def validate_objective_facts(players, fan_card, hand_counts, f_yj_who, f_yj_res, f_yj_tar, f_b8_who, f_b8_res, f_b8_tar,
                             e_yj, e_b8, gang_data):
    if fan_card and sum(hand_counts.get(p, 0) for p in players) > 4: raise ValueError("翻鸡总数超过4张")

    def check_tile(name, f_who, f_res, f_tar, extra_map):
        total = sum(extra_map.get(p, 0) for p in players)
        gangs = [g for g in gang_data if g['card'] == name and g['type'] in ["暗杠", "补杠", "普通明杠", "责任明杠"]]
        consumed = 0
        if f_who and f_who != "无/未现":
            if f_res == "被碰":
                consumed = 3
            elif f_res == "被明杠":
                consumed = 4
            elif f_res == "被胡":
                consumed = 1
            else:
                consumed = 1

        bu_gangs = [g for g in gangs if g['type'] == "补杠"]
        if bu_gangs:
            if len(bu_gangs) > 1: raise ValueError(f"{name}补杠重复")
            if not (f_who and f_res == "被碰"): raise ValueError(f"{name}补杠需基于首出被碰")
            if bu_gangs[0]['doer'] != f_tar: raise ValueError(f"{name}补杠者必须是碰牌者")

        if gangs or (f_who and f_res == "被明杠"):
            if total != 0: raise ValueError(f"{name}有杠时，非首出应为0")
        else:
            if consumed + total > 4: raise ValueError(f"{name}总数超限(>4)")

    check_tile("幺鸡", f_yj_who, f_yj_res, f_yj_tar, e_yj)
    check_tile("八筒", f_b8_who, f_b8_res, f_b8_tar, e_b8)


def validate_consistency(players, winners, method, fyw, fyr, fyt, fbw, fbr, fbt, gang_data):
    if method == "自摸" and (fyr == "被胡" or fbr == "被胡"): raise ValueError("自摸不能接首出胡")
    if fyr == "被胡" and fbr == "被胡": raise ValueError("双常鸡不能同时被胡")

    def check_gang_conflict(tile, res):
        has_gang = any(g['card'] == tile for g in gang_data if g['type'] in ["暗杠", "补杠", "普通明杠", "责任明杠"])
        if res == "被胡" and has_gang: raise ValueError(f"{tile}被胡时不能有杠")
        if has_gang and res == "被胡": raise ValueError(f"{tile}有杠时不能被胡")

    check_gang_conflict("幺鸡", fyr);
    check_gang_conflict("八筒", fbr)


# -------------------------------
# 4. 核心计算管道
# -------------------------------
def calculate_all_pipeline(
        players, winners, method, loser, hu_shape, is_qing, special_events, rules_config,
        fan_card, ready_list, fyw, fyr, fyt, fbw, fbr, fbt, extra_yj, extra_b8,
        hand_total_counts, gang_data, common_v, fan_unit
) -> Tuple[Dict[str, int], Dict[str, List[str]]]:
    raw_txs = []
    winners_set = set(winners)
    ready_set = set([p for p in ready_list if p in players]) | winners_set

    # 1. Validation
    validate_objective_facts(players, fan_card, hand_total_counts, fyw, fyr, fyt, fbw, fbr, fbt, extra_yj, extra_b8,
                             gang_data)
    validate_consistency(players, winners, method, fyw, fyr, fyt, fbw, fbr, fbt, gang_data)

    get_price = lambda c: int(common_v.get(c, 0))

    # 2. Score Calculation
    # 2.1 Hu
    if winners:
        base = rules_config.get(hu_shape, 0) + (rules_config.get("清一色加成", 0) if is_qing else 0)
        spec = sum(rules_config.get(e, 0) for e in special_events)
        total = base + spec
        desc = f"{hu_shape}" + ("+清" if is_qing else "") + (f"+{'+'.join(special_events)}" if special_events else "")
        if method == "自摸":
            for p in players:
                if p != winners[0]: raw_txs.append(Transaction(p, winners[0], total, f"自摸({desc})", "hu"))
        elif method == "点炮" and loser:
            for w in winners: raw_txs.append(Transaction(loser, w, total, f"点炮({desc})", "hu"))

    # 2.2 Gang
    for g in gang_data:
        d, t, v, c = g['doer'], g['type'], g['victim'], g['card']
        if not d: continue
        score = 4 if t == "暗杠" else 2
        if t in ["暗杠", "补杠"]:
            for p in players:
                if p != d: raw_txs.append(Transaction(p, d, score, f"{t}-{c}", "gang"))
        elif v and v in players:
            raw_txs.append(Transaction(v, d, score, f"{t}-{c}", "gang"))

    # 2.3 Fan Chicken
    for i in range(len(players)):
        for j in range(i + 1, len(players)):
            p1, p2 = players[i], players[j]
            c1, c2 = hand_total_counts.get(p1, 0), hand_total_counts.get(p2, 0)
            if c1 != c2:
                win, los = (p1, p2) if c1 > c2 else (p2, p1)
                raw_txs.append(Transaction(los, win, abs(c1 - c2) * fan_unit, "翻鸡互斥", "chicken_fan_luck"))

    # 2.4 Common Chicken
    # Charge
    for card, who, res in [("幺鸡", fyw, fyr), ("八筒", fbw, fbr)]:
        if who and who != "无/未现" and res == "安全":
            u = get_price(card)
            if u > 0:
                for p in players:
                    if p != who: raw_txs.append(Transaction(p, who, u * 2, f"冲锋鸡-{card}", "chicken_charge"))

    # Extra (Split)
    for card, e_map in [("幺鸡", extra_yj), ("八筒", extra_b8)]:
        u = get_price(card)
        if u > 0:
            for owner, count in e_map.items():
                if count > 0:
                    for p in players:
                        if p != owner: raw_txs.append(
                            Transaction(p, owner, count * u, f"常鸡-{card}({count}张)", "chicken_extra"))

    # Landed
    landed = []
    for g in gang_data:
        if g['card'] in ["幺鸡", "八筒"]:
            vic = g['victim']
            if g['type'] == "补杠":
                if g['card'] == "幺鸡" and fyr == "被碰" and fyt == g['doer']:
                    vic = fyw
                elif g['card'] == "八筒" and fbr == "被碰" and fbt == g['doer']:
                    vic = fbw
            landed.append({'o': g['doer'], 'c': g['card'], 'n': 4, 'v': vic, 't': g['type']})

    # Add Peng
    if fyr == "被碰" and fyt and not any(
            g['card'] == "幺鸡" and g['type'] == "补杠" and g['doer'] == fyt for g in gang_data):
        landed.append({'o': fyt, 'c': "幺鸡", 'n': 3, 'v': fyw, 't': "碰"})
    if fbr == "被碰" and fbt and not any(
            g['card'] == "八筒" and g['type'] == "补杠" and g['doer'] == fbt for g in gang_data):
        landed.append({'o': fbt, 'c': "八筒", 'n': 3, 'v': fbw, 't': "碰"})

    # Add Hu
    def add_h(c, r, t, v):
        if r == "被胡" and t:
            for tar in (t if isinstance(t, list) else [t]): landed.append({'o': tar, 'c': c, 'n': 1, 'v': v, 't': "胡"})

    add_h("幺鸡", fyr, fyt, fyw);
    add_h("八筒", fbr, fbt, fbw)

    for l in landed:
        o, c, n, v, t = l['o'], l['c'], l['n'], l['v'], l['t']
        u = get_price(c)
        if u <= 0: continue
        for p in players:
            if p == o: continue
            is_liable = (v and p == v)
            amt = (2 * u) + (u * (n - 1)) if is_liable else (u * n)
            reason = f"{t}鸡-{c}({n}张{',责任' if is_liable else ''})"
            raw_txs.append(Transaction(p, o, amt, reason, "chicken_resp"))

    # 3. Filter
    final = []
    zero_income = set()
    if method == "点炮" and loser and ("热炮" in special_events or "抢杠胡" in special_events) and loser in ready_set:
        zero_income.add(loser)

    for tx in raw_txs:
        if tx.receiver in zero_income: continue
        if tx.receiver in ready_set:
            final.append(tx)
        else:
            if tx.category in ["gang", "chicken_charge", "chicken_resp", "chicken_extra"]:
                if tx.payer in ready_set: final.append(tx.reverse())
            else:
                pass

    scores = {p: 0 for p in players}
    details = {p: [] for p in players}
    for tx in final:
        scores[tx.receiver] += tx.amount
        scores[tx.payer] -= tx.amount
        details[tx.receiver].append(f"{tx.reason}: +{tx.amount} ({tx.payer})")
        details[tx.payer].append(f"{tx.reason}: -{tx.amount} ({tx.receiver})")

    return scores, details


# ==============================================================================
# UI (V45 - 全功能回归 + iOS优化)
# ==============================================================================

def main():
    st.set_page_config(page_title="捉鸡Pro", page_icon="🀄", layout="wide", initial_sidebar_state="collapsed")
    init_app_state()

    main_round = st.session_state["main_round"]

    # --- UI 辅助函数 (已找回) ---
    def ui_section(title: str, icon: str = "", caption: Optional[str] = None):
        cap_html = f'<span class="glass-caption">{caption}</span>' if caption else ""
        st.markdown(f'<div class="glass-header"><span class="glass-header-icon">{icon}</span> {title}{cap_html}</div>',
                    unsafe_allow_html=True)

    def ui_divider(label: Optional[str] = None):
        if label:
            st.markdown(f'<div class="ui-divider"><span>{label}</span></div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="ui-divider" style="margin-top:10px;"></div>', unsafe_allow_html=True)

    K = lambda s: f"main_{main_round}_{s}"

    # --- 侧边栏：恢复全局设置与规则 ---
    with st.sidebar:
        st.markdown("### ⚙️ 全局设置")
        # 1. 玩家改名
        with st.expander("👥 玩家署名", expanded=True):
            new_names = []
            for i, n in enumerate(st.session_state.p_names):
                new_names.append(st.text_input(f"座位 {i + 1}", n, key=f"pn_{i}"))
            if new_names != st.session_state.p_names:
                st.session_state.p_names = new_names
                st.rerun()

        players = st.session_state.p_names  # 更新

        # 2. 规则分值
        rules_config: Dict[str, int] = {}
        with st.expander("🔧 规则分值", expanded=False):
            c_r1, c_r2 = st.columns(2)
            rules_config["平胡"] = c_r1.number_input("平胡", 5, step=1)
            rules_config["大对子"] = c_r2.number_input("大对子", 15, step=1)
            rules_config["七对"] = c_r1.number_input("七对", 25, step=1)
            rules_config["龙七对"] = c_r2.number_input("龙七对", 50, step=1)
            rules_config["清一色加成"] = st.number_input("清一色加分", 25, step=5)
            st.markdown("---")
            default_events = {"报听胡": 25, "杀报": 50, "杠上花": 25, "抢杠胡": 25, "热炮": 25, "天胡": 75, "地胡": 50}
            for k, v in default_events.items():
                rules_config[k] = st.number_input(f"{k}", v, step=5)

        # 3. 常鸡价值
        with st.expander("🐔 常鸡价值", expanded=False):
            c1, c2 = st.columns(2)
            with c1:
                base_yj = st.number_input("1条 底分", 2)
                mul_yj = st.number_input("1条 倍数", 1)
            with c2:
                base_b8 = st.number_input("8筒 底分", 2)
                mul_b8 = st.number_input("8筒 倍数", 1)

        # 4. 翻鸡单位
        with st.expander("🖐️ 翻鸡单位", expanded=False):
            fan_unit = st.number_input("互斥单位分", 1)

        st.divider()

        # 5. 历史记录与导出 (保留之前的逻辑)
        st.markdown("### 📜 历史记录")
        ledger = st.session_state["ledger_data"]

        if ledger:
            # 导出
            df = pd.DataFrame([r['scores'] for r in ledger])
            df.insert(0, "局", [r['round'] for r in ledger])
            csv = df.to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 导出表格", csv, "results.csv", "text/csv", use_container_width=True)

            # 历史列表
            for rec in reversed(ledger):
                s_txt = " | ".join([f"{p}:{rec['scores'][p]}" for p in players])
                label = f"第{rec['round']}局: {s_txt}"
                with st.expander(label):
                    st.caption(f"{rec['summary']}")
                    for p in players:
                        if rec['details'][p]:
                            st.markdown(f"**{p}**")
                            for l in rec['details'][p]: st.text(l)
        else:
            st.caption("暂无数据")

    # --- CSS 样式 ---
    st.markdown("""
        <style>
        /* iOS Optimization */
        input, select, textarea, button { font-size: 16px !important; } 
        div[data-baseweb="select"] > div { min-height: 44px; }
        .stNumberInput input { min-height: 44px; }
        .stButton button { min-height: 48px; border-radius: 12px !important; font-weight: bold !important; }
        :root { --bg-dark: #0e1117; --glass: rgba(255, 255, 255, 0.05); --border: rgba(255, 255, 255, 0.1); }
        .stApp { background-color: var(--bg-dark); }
        .glass-header { 
            font-size: 1.15rem; font-weight: 800; color: #fff; 
            padding: 10px 0; margin-bottom: 8px; border-bottom: 1px solid var(--border);
            display: flex; align-items: center; gap: 8px;
        }
        .mini-score-card {
            background: var(--glass); border: 1px solid var(--border); border-radius: 12px;
            padding: 8px 12px; text-align: center; margin-bottom: 8px;
        }
        .mini-score-val { font-size: 1.1rem; font-weight: 700; color: #4ed9ff; }
        .mini-score-label { font-size: 0.75rem; color: #aaa; }
        .chip { 
            padding: 4px 10px; border-radius: 20px; font-size: 0.8rem; font-weight: 600;
            background: var(--glass); border: 1px solid var(--border); color: #ccc;
        }
        .chip.ok { border-color: #00c853; color: #b9f6ca; background: rgba(0, 200, 83, 0.1); }
        .chip.warn { border-color: #ffd600; color: #fff9c4; background: rgba(255, 214, 0, 0.1); }
        .holo-ticket { padding: 12px 16px; margin-bottom: 10px; border-radius: 18px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.14); box-shadow: 0 4px 12px rgba(0,0,0,0.2); }
        .tx-pay, .tx-get { font-weight:bold; } .tx-arrow { color: #888; margin: 0 8px; } .tx-amt-box { margin-left: auto; font-family: monospace; font-weight: bold; color: #4ed9ff; }
        [data-testid="stVerticalBlockBorderWrapper"] { padding: 12px !important; border-radius: 16px !important; }
        .block-container { padding-top: 2rem; padding-bottom: 3rem; }
        .sticky-panel { position: sticky; top: 14px; z-index: 5; }
        .action-bar { background: rgba(18,22,32,0.85); border: 1px solid rgba(255,255,255,0.14); border-radius: 20px; padding: 12px; backdrop-filter: blur(20px); margin-bottom: 14px; }
        #MainMenu {visibility: hidden;} header {visibility: hidden;} footer {visibility: hidden;}
        </style>
    """, unsafe_allow_html=True)

    # --- 顶部迷你计分板 ---
    total_scores = {p: 0 for p in players}
    for r in st.session_state["ledger_data"]:
        for p, s in r['scores'].items(): total_scores[p] += s

    cols_top = st.columns(4)
    for i, p in enumerate(players):
        with cols_top[i]:
            val = total_scores[p]
            color = "#ff4b4b" if val < 0 else "#00c853" if val > 0 else "#aaa"
            st.markdown(
                f"""<div class="mini-score-card"><div class="mini-score-label">{p}</div><div class="mini-score-val" style="color:{color}">{val}</div></div>""",
                unsafe_allow_html=True)

    # --- 主界面 ---
    left, right = st.columns([1.3, 0.7], gap="large")

    with left:
        # 1. 胜负
        with st.container(border=True):
            ui_section("本局胜负", "🏆")
            c_f1, c_f2, c_f3 = st.columns([1.5, 1.5, 1])
            with c_f1:
                is_fan = st.checkbox("有翻牌?", True, key=K("is_fan"))
            fan_card = ""
            if is_fan:
                with c_f2: f_num = st.selectbox("点", range(1, 10), key=K("fn"), label_visibility="collapsed")
                with c_f3: f_suit = st.selectbox("花", ["筒", "条", "万"], key=K("fs"), label_visibility="collapsed")
                fan_card = f"{f_num}{f_suit}"

            c_w1, c_w2 = st.columns([2, 1.5])
            with c_w1:
                winners = st.multiselect("🎉 胡牌者", players, key=K("winners"))
            with c_w2:
                method = st.radio("方式", ["自摸", "点炮"], horizontal=True, key=K("method"))

            loser = None
            if method == "点炮":
                loser = st.selectbox("💥 点炮者", [p for p in players if p not in winners], key=K("loser"))
                if not loser and winners: st.error("必选点炮者")
            elif method == "自摸" and len(winners) > 1:
                st.error("自摸只能1人")

            hu_shape, is_qing, special_events = "平胡", False, []
            if winners:
                with st.expander("📋 牌型细节", expanded=True):
                    c1, c2 = st.columns(2)
                    hu_shape = c1.selectbox("牌型", ["平胡", "大对子", "七对", "龙七对"], key=K("shape"))
                    is_qing = c2.checkbox("清一色", key=K("qing"))
                    ev_opts = ["报听胡", "杀报", "杠上花", "热炮", "抢杠胡", "天胡", "地胡"]
                    if method == "自摸": ev_opts = [e for e in ev_opts if e not in ["热炮", "抢杠胡"]]
                    special_events = st.multiselect("事件", ev_opts, key=K("ev"))

        # 2. 听牌
        with st.container(border=True):
            ui_section("听牌状态", "👂")
            ready_list = st.multiselect("谁听牌了?", players, default=players, key=K("ready"))

        # 3. 首出 (动态计算常鸡价值)
        common_v = build_common_chicken_cfg(base_yj, mul_yj, base_b8, mul_b8, fan_card)

        with st.container(border=True):
            ui_section(f"首出 (1条:{common_v['幺鸡']} / 8筒:{common_v['八筒']})", "🚀")
            if st.session_state.get(K("fyr")) == "被胡" and st.session_state.get(K("fbr")) == "被胡": st.session_state[
                K("fbr")] = "安全"

            c1, c2 = st.columns([1, 2])
            with c1:
                fyw = st.selectbox("1条 首出", ["无/未现"] + players, key=K("fyw"))
            fyr, fyt = "安全", None
            if fyw != "无/未现":
                with c2:
                    opts = ["安全", "被碰", "被明杠", "被胡"]
                    if method == "自摸" or st.session_state.get(K("fbr")) == "被胡": opts = ["安全", "被碰", "被明杠"]
                    fyr = st.radio("1条 结局", opts, horizontal=True, key=K("fyr"))
                    if fyr == "被胡":
                        fyt = [w for w in winners if w in players]
                        st.caption(f"-> {','.join(fyt) if fyt else '?'}")
                    elif fyr != "安全":
                        fyt = st.selectbox("被谁?", [p for p in players if p != fyw], key=K("fyt"))

            st.markdown("---")
            c3, c4 = st.columns([1, 2])
            with c3:
                fbw = st.selectbox("8筒 首出", ["无/未现"] + players, key=K("fbw"))
            fbr, fbt = "安全", None
            if fbw != "无/未现":
                with c4:
                    opts = ["安全", "被碰", "被明杠", "被胡"]
                    if method == "自摸" or st.session_state.get(K("fyr")) == "被胡": opts = ["安全", "被碰", "被明杠"]
                    fbr = st.radio("8筒 结局", opts, horizontal=True, key=K("fbr"))
                    if fbr == "被胡":
                        fbt = [w for w in winners if w in players]
                        st.caption(f"-> {','.join(fbt) if fbt else '?'}")
                    elif fbr != "安全":
                        fbt = st.selectbox("被谁?", [p for p in players if p != fbw], key=K("fbt"))

        # 4. 常鸡
        with st.container(border=True):
            ui_section("常鸡 (非首出)", "🔢")
            extra_yj, extra_b8 = {}, {}
            cols = st.columns(4)
            for i, p in enumerate(players):
                with cols[i]:
                    st.caption(f"**{p}**")
                    extra_yj[p] = st.number_input(f"1条", 0, 4, 0, key=K(f"ey_{i}"), label_visibility="collapsed")
                    extra_b8[p] = st.number_input(f"8筒", 0, 4, 0, key=K(f"eb_{i}"), label_visibility="collapsed")

        # 5. 翻鸡
        with st.container(border=True):
            ui_section("翻鸡 (手牌+桌面)", "🖐️")
            hand_total_counts = {}
            if fan_card in ["9条", "7筒"]:
                st.info("翻倍鸡规则：不互斥")
            else:
                cols = st.columns(4)
                for i, p in enumerate(players):
                    with cols[i]:
                        st.caption(f"**{p}**")
                        hand_total_counts[p] = st.number_input(f"fc", 0, 4, 0, key=K(f"fc_{i}"),
                                                               label_visibility="collapsed")

        # 6. 杠牌
        with st.container(border=True):
            ui_section("杠牌登记", "🛠️")
            gang_data = []

            auto_gangs = []
            if fyw != "无/未现" and fyr == "被明杠" and fyt: auto_gangs.append(f"{fyt} 杠 {fyw} (幺鸡)")
            if fbw != "无/未现" and fbr == "被明杠" and fbt: auto_gangs.append(f"{fbt} 杠 {fbw} (八筒)")
            if auto_gangs:
                for ag in auto_gangs: st.info(f"⚡ 自动: {ag}")

            for i in range(st.session_state.gang_rows):
                c1, c2, c3, c4 = st.columns([1.5, 1.5, 1.5, 1.5])
                with c1:
                    gw = st.selectbox("杠主", ["无"] + players, key=K(f"gw{i}"))
                if gw != "无":
                    with c2:
                        gt = st.selectbox("类型", ["暗杠", "补杠", "普通明杠"], key=K(f"gt{i}"))
                    with c3:
                        gc = st.selectbox("牌", ["杂牌", "幺鸡", "八筒"] if gt != "补杠" else ["杂牌"], key=K(f"gc{i}"))
                    with c4:
                        gv = None
                        if gt == "普通明杠": gv = st.selectbox("被杠", [p for p in players if p != gw], key=K(f"gv{i}"))
                    gang_data.append({'doer': gw, 'type': gt, 'card': gc, 'victim': gv})

            if fyw != "无/未现" and fyr == "被明杠" and fyt: gang_data.append(
                {'doer': fyt, 'type': '责任明杠', 'card': '幺鸡', 'victim': fyw})
            if fbw != "无/未现" and fbr == "被明杠" and fbt: gang_data.append(
                {'doer': fbt, 'type': '责任明杠', 'card': '八筒', 'victim': fbw})

            if fyw != "无/未现" and fyr == "被碰" and fyt:
                if st.checkbox(f"幺鸡补杠 ({fyt})", key=K("yj_bu")):
                    gang_data.append({'doer': fyt, 'type': '补杠', 'card': '幺鸡', 'victim': None})
            if fbw != "无/未现" and fbr == "被碰" and fbt:
                if st.checkbox(f"八筒补杠 ({fbt})", key=K("b8_bu")):
                    gang_data.append({'doer': fbt, 'type': '补杠', 'card': '八筒', 'victim': None})

            if st.button("➕ 增加一条杠", key=K("add_gang")):
                st.session_state.gang_rows += 1
                st.rerun()

    # ================== 操作控制台 ==================
    with right:
        st.markdown('<div class="sticky-panel">', unsafe_allow_html=True)
        st.markdown('<div class="action-bar">', unsafe_allow_html=True)
        st.markdown('<div class="glass-header">⚡️ 操作台</div>', unsafe_allow_html=True)

        c_a1, c_a2 = st.columns(2)
        with c_a1:
            settle = st.button("💰 试算", use_container_width=True, key=K("settle"))
        with c_a2:
            reset = st.button("🔄 重置", use_container_width=True, key=K("reset"))
        confirm = st.button("✅ 记账 & 下一局", type="primary", use_container_width=True, key=K("confirm"))
        st.markdown('</div>', unsafe_allow_html=True)

        if reset: next_round()

        valid = True
        if not winners: valid = False
        if method == "点炮" and not loser: valid = False

        if settle or confirm:
            if not valid:
                st.error("❌ 信息不完整：请检查胡牌者/点炮者")
            else:
                try:
                    # ⚠️ 关键修正：从侧边栏的 rules_config 传入逻辑，而不是硬编码
                    scores, details = calculate_all_pipeline(
                        players, winners, method, loser, hu_shape, is_qing, special_events, rules_config,
                        fan_card, ready_list, fyw, fyr, fyt, fbw, fbr, fbt, extra_yj, extra_b8,
                        hand_total_counts, gang_data, common_v, fan_unit
                    )

                    with st.container(border=True):
                        ui_section("结算", "🧾")
                        cols_s = st.columns(2)
                        for i, p in enumerate(players):
                            s = scores[p]
                            color = "green" if s > 0 else "red" if s < 0 else "off"
                            cols_s[i % 2].metric(p, int(s), delta=int(s))

                        st.caption("转账流水")
                        cred = sorted([[k, v] for k, v in scores.items() if v > 0], key=lambda x: x[1], reverse=True)
                        debt = sorted([[k, -v] for k, v in scores.items() if v < 0], key=lambda x: x[1], reverse=True)
                        i, j = 0, 0
                        while i < len(debt) and j < len(cred):
                            dn, da = debt[i];
                            cn, ca = cred[j]
                            amt = min(da, ca)
                            if amt > 0:
                                st.markdown(
                                    f"**{dn}** ➜ **{cn}** : <span style='color:#4ed9ff; font-weight:bold'>¥{int(amt)}</span>",
                                    unsafe_allow_html=True)
                            debt[i][1] -= amt;
                            cred[j][1] -= amt
                            if debt[i][1] < 0.1: i += 1
                            if cred[j][1] < 0.1: j += 1

                        with st.expander("📄 查看详细账单"):
                            for p in players:
                                if details[p]:
                                    st.markdown(f"**{p}**")
                                    for line in details[p]:
                                        color = "red" if ": -" in line else "green"
                                        st.markdown(f"- :{color}[{line}]")

                    if confirm:
                        summary = f"{' & '.join(winners)} {method}" + (f" ({loser})" if loser else "")
                        rec = {
                            "round": main_round + 1,
                            "summary": summary,
                            "scores": scores,
                            "details": details
                        }
                        st.session_state["ledger_data"].append(rec)
                        st.toast("✅ 已记账！", icon="💾")
                        time.sleep(0.8)
                        next_round()

                except ValueError as e:
                    st.error(str(e))

        st.markdown('</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
