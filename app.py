import streamlit as st
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple
import os


# ==============================================================================
# 🧠 Logic Kernel (V25 - 碰牌剩余双轨制修复版)
# ==============================================================================
# -------------------------------
# Reset helper
# -------------------------------
def reset_main_ui_state():
    st.session_state["main_round"] = int(st.session_state.get("main_round", 0)) + 1
    st.session_state["gang_rows"] = 1


# -------------------------------
# Utilities
# -------------------------------
def parse_card(card_str: str) -> Optional[Tuple[int, str]]:
    if not card_str: return None
    try:
        suit = card_str[-1];
        num = int(card_str[:-1])
        if suit not in ["筒", "条", "万"]: return None
        if num < 1 or num > 9: return None
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
class Transfer:
    receiver: str;
    payer: str;
    amount: int;
    reason: str


def add_transfer(transfers: List[Transfer], receiver: str, payer: str, amount: int, reason: str):
    if receiver == payer or amount <= 0: return
    transfers.append(Transfer(receiver=receiver, payer=payer, amount=int(amount), reason=reason))


def build_common_chicken_cfg(base_yj: int, mul_yj: int, base_b8: int, mul_b8: int, fan_card) -> Dict[str, int]:
    fan_mul_yj, fan_mul_b8 = get_fan_multipliers(fan_card)
    return {"幺鸡": int(base_yj) * int(mul_yj) * int(fan_mul_yj), "八筒": int(base_b8) * int(mul_b8) * int(fan_mul_b8)}


# -------------------------------
# Logic: Objective Validation
# -------------------------------
def _validate_fan_counts_max4(players: List[str], fan_card: str, hand_total_counts: Dict[str, int]):
    if not fan_card: return
    total = sum(int(hand_total_counts.get(p, 0)) for p in players)
    if total > 4: raise ValueError(f"翻鸡总数不可能超过4：当前合计={total}")


def _first_outcome_consumed(first_who: str, first_res: str) -> int:
    if not first_who or first_who == "无/未现": return 0
    if first_res == "被碰": return 3
    if first_res == "被明杠": return 4
    return 1


def _has_tile_gang(gang_data: List[Dict], tile_name: str) -> List[Dict]:
    return [g for g in gang_data if
            g.get("card") == tile_name and g.get("type") in ["暗杠", "补杠", "普通明杠", "责任明杠"]]


def _validate_common_tile_max4(tile_name, players, first_who, first_res, first_tar, extra_map, gang_data):
    extras_total = sum(int(extra_map.get(p, 0)) for p in players)
    tile_gangs = _has_tile_gang(gang_data, tile_name)

    bu_gangs = [g for g in tile_gangs if g.get("type") == "补杠"]
    if bu_gangs:
        if len(bu_gangs) != 1: raise ValueError(f"{tile_name} 补杠记录重复。")
        if not (first_who and first_who != "无/未现" and first_res == "被碰"):
            raise ValueError(f"{tile_name} 出现补杠时，首出结局必须为‘被碰’。")
        if bu_gangs[0].get("doer") != first_tar:
            raise ValueError(f"{tile_name} 补杠者必须为碰牌者。")
        other_gangs = [g for g in tile_gangs if g.get("type") in ["暗杠", "普通明杠", "责任明杠"]]
        if other_gangs:
            raise ValueError(f"{tile_name} 已登记补杠时，不允许再登记其他杠型。")

    consumed = _first_outcome_consumed(first_who, first_res)
    if tile_gangs or (first_who and first_who != "无/未现" and first_res == "被明杠"):
        if extras_total != 0:
            raise ValueError(f"{tile_name} 出现杠时，手牌常鸡必须全为0。")

        # 验证被明杠的一致性
        if first_who and first_who != "无/未现" and first_res == "被明杠":
            if not first_tar or first_tar == first_who:
                raise ValueError(f"{tile_name} 首出为‘被明杠’时，必须填写‘被谁?’（杠主）。")
            ok = False
            for g in tile_gangs:
                if g.get("type") == "责任明杠" and g.get("doer") == first_tar and g.get("victim") == first_who:
                    ok = True
                    break
            if not ok:
                raise ValueError(f"{tile_name} 首出为‘被明杠’时，杠牌登记需存在对应责任明杠记录。")
        return

    if consumed == 0 and extras_total > 4:
        raise ValueError(f"{tile_name} 总数超限（全场最多4张）。")

    if first_res == "被碰":
        if extras_total > 1:
            raise ValueError(f"{tile_name} 被碰后全场剩余最多1张。")
    else:
        # 安全/被胡
        if consumed > 0 and extras_total > 3:
            raise ValueError(f"{tile_name} 打出后全场剩余最多3张。")

    if consumed + extras_total > 4:
        raise ValueError(f"{tile_name} 总数超限：首出占用={consumed}, 手牌合计={extras_total}。")


def validate_objective_facts(*, players, fan_card, hand_total_counts, first_yj_who, first_yj_res, first_yj_tar,
                             first_b8_who, first_b8_res, first_b8_tar, extra_yj, extra_b8, gang_data):
    _validate_fan_counts_max4(players, fan_card, hand_total_counts)
    _validate_common_tile_max4("幺鸡", players, first_yj_who, first_yj_res, first_yj_tar, extra_yj, gang_data)
    _validate_common_tile_max4("八筒", players, first_b8_who, first_b8_res, first_b8_tar, extra_b8, gang_data)


def validate_winner_and_event_consistency(
        *, players, winners, method, first_yj_who, first_yj_res, first_yj_tar,
        first_b8_who, first_b8_res, first_b8_tar, gang_data
):
    winners_set = set([w for w in winners if w in players])

    if method == "自摸":
        if first_yj_res == "被胡" or first_b8_res == "被胡":
            raise ValueError("自摸成立时，不存在‘首出常鸡被胡’。")

    def _is_hu(res: str) -> bool:
        return res == "被胡"

    if _is_hu(first_yj_res) and _is_hu(first_b8_res):
        raise ValueError("幺鸡与八筒不可能同时被胡。")

    def _tar_list(tar):
        if tar is None: return []
        if isinstance(tar, list): return [t for t in tar if t]
        return [tar]

    def _require_first_out(tile_name: str, who: str, res: str):
        if res in ["被碰", "被明杠", "被胡"]:
            if not who or who == "无/未现":
                raise ValueError(f"{tile_name} 结局为‘{res}’时，首出者不能为‘无/未现’。")

    _require_first_out("幺鸡", first_yj_who, first_yj_res)
    _require_first_out("八筒", first_b8_who, first_b8_res)

    def _validate_hu_target(tile_name: str, res: str, tar):
        if res != "被胡": return
        if not winners_set:
            raise ValueError(f"已选择 {tile_name} ‘被胡’，但胡牌者为空。")
        tl = _tar_list(tar)
        if set(tl) != winners_set:
            raise ValueError(f"{tile_name} ‘被胡’必须继承胡牌者名单。")

    _validate_hu_target("幺鸡", first_yj_res, first_yj_tar)
    _validate_hu_target("八筒", first_b8_res, first_b8_tar)

    def _has_any_gang(tile_name: str) -> bool:
        for g in gang_data:
            if g.get("card") == tile_name and g.get("type") in ["暗杠", "补杠", "普通明杠", "责任明杠"]:
                return True
        return False

    if _is_hu(first_yj_res) and _has_any_gang("幺鸡"):
        raise ValueError("幺鸡已被胡，不允许再有杠。")
    if _is_hu(first_b8_res) and _has_any_gang("八筒"):
        raise ValueError("八筒已被胡，不允许再有杠。")
    if _has_any_gang("幺鸡") and _is_hu(first_yj_res):
        raise ValueError("幺鸡有杠，不允许被胡。")
    if _has_any_gang("八筒") and _is_hu(first_b8_res):
        raise ValueError("八筒有杠，不允许被胡。")


# -------------------------------
# Logic: Settlement Functions
# -------------------------------

def settle_hu(players, winners, method, loser, hu_shape, is_qing, special_events, rules_config) -> List[Transfer]:
    transfers = []
    if not winners: return transfers
    base = int(rules_config.get(hu_shape, 0)) + (int(rules_config.get("清一色加成", 0)) if is_qing else 0)
    spec = sum(int(rules_config.get(e, 0)) for e in special_events)
    total = base + spec
    desc = f"{hu_shape}{'+清' if is_qing else ''}{'+' + '+'.join(special_events) if special_events else ''}"
    if method == "自摸":
        w = winners[0]
        for p in players:
            if p != w: add_transfer(transfers, w, p, total, f"自摸({desc})")
    else:
        if loser:
            for w in winners: add_transfer(transfers, w, loser, total, f"点炮({desc})")
    return transfers


def settle_fan_chicken_pairwise(pay_set, receive_set, hand_counts, unit=1) -> List[Transfer]:
    transfers = []
    el = sorted(list(pay_set))
    eff = lambda p: int(hand_counts.get(p, 0)) if p in receive_set else 0
    for i in range(len(el)):
        for j in range(i + 1, len(el)):
            a, b = el[i], el[j]
            ca, cb = eff(a), eff(b)
            if ca == cb: continue
            if ca > cb:
                if a in receive_set: add_transfer(transfers, a, b, (ca - cb) * unit, "🖐️ 翻鸡")
            elif cb > ca:
                if b in receive_set: add_transfer(transfers, b, a, (cb - ca) * unit, "🖐️ 翻鸡")
    return transfers


def settle_gang_base_points(gang_data, eligible_set, burn_ready_player, not_ready_set) -> List[Transfer]:
    """
    4. 杠牌基础分 (Action Score)
    规则：
    - 暗杠(4)/补杠(2)：全场结算（听牌收钱，未听赔钱）。
    - 明杠(2)：仅杠主与被杠人结算（听牌收钱，未听赔钱）。
    """
    transfers = []
    valid_receivers = set(eligible_set)
    if burn_ready_player: valid_receivers.discard(burn_ready_player)

    # 支付者包含所有未赢的人（含未听牌）
    players = list(valid_receivers | not_ready_set)

    for g in gang_data:
        doer, gtype, victim = g.get('doer'), g.get('type'), g.get('victim')
        if not doer: continue
        base_g = 4 if gtype == "暗杠" else 2

        # A) 杠主听牌：收取分值
        if doer in valid_receivers:
            if gtype in ["暗杠", "补杠"]:
                # 全场支付
                for p in players:
                    if p != doer:
                        add_transfer(transfers, doer, p, base_g, f"{gtype}(基础分)")
            elif gtype in ["普通明杠", "责任明杠"]:
                # 仅被杠人支付
                if victim and victim in players and victim != doer:
                    add_transfer(transfers, doer, victim, base_g, "明杠(基础分)")

        # B) 杠主未听牌：反向赔付
        elif doer in not_ready_set:
            if gtype in ["暗杠", "补杠"]:
                # 赔给所有听牌者
                for p in valid_receivers:
                    add_transfer(transfers, p, doer, base_g, f"未听牌-{gtype}赔付")
            elif gtype in ["普通明杠", "责任明杠"]:
                # 仅赔给听牌的被杠人
                if victim and victim in valid_receivers and victim != doer:
                    add_transfer(transfers, victim, doer, base_g, "未听牌-明杠赔付")

    return transfers


def settle_common_first_responsibility(pay_set, receive_set, common_v, card_name, who, res, tar) -> List[Transfer]:
    """责任鸡结算 (1张，2倍赔付，仅限打出者 who 赔付)"""
    transfers = []
    if not (who and who != "无/未现"): return transfers
    if res not in ["被碰", "被明杠", "被胡"] or not tar: return transfers
    v = int(common_v.get(card_name, 0))
    if v <= 0: return transfers

    targets = tar if isinstance(tar, list) else [tar]
    for t in targets:
        if not t: continue
        # 正常逻辑：收者听牌，付者在场，且支付者是打牌者(who)
        if t in receive_set and who in pay_set and t != who:
            add_transfer(transfers, t, who, 2 * v, f"🔥 责任鸡赔付-{card_name}({res},×2)")

    return transfers


def settle_charge_chicken_pairwise(pay_set, receive_set, common_v, card, who, res) -> List[Transfer]:
    """冲锋鸡结算"""
    transfers = []
    v = int(common_v.get(card, 0))
    if v <= 0: return transfers
    has_charge = {p: 0 for p in pay_set}
    if who and who != "无/未现" and res == "安全" and who in receive_set: has_charge[who] = 1

    el = sorted(list(pay_set))
    for i in range(len(el)):
        for j in range(i + 1, len(el)):
            a, b = el[i], el[j]
            va = has_charge.get(a, 0) * 2 * v
            vb = has_charge.get(b, 0) * 2 * v
            if va > vb and a in receive_set:
                add_transfer(transfers, a, b, va - vb, f"🏁 冲锋鸡互斥-{card}")
            elif vb > va and b in receive_set:
                add_transfer(transfers, b, a, vb - va, f"🏁 冲锋鸡互斥-{card}")
    return transfers


def build_hand_chicken_totals(players, receive_set, common_v, ey, eb):
    """手牌常鸡统计 (V21: 仅计算手牌)"""
    totals = {p: 0 for p in players}
    v_map = {"幺鸡": int(common_v.get("幺鸡", 0)), "八筒": int(common_v.get("八筒", 0))}
    for cname, emap in [("幺鸡", ey), ("八筒", eb)]:
        if v_map[cname] > 0:
            for p in players:
                # 只有听牌者才拥有有效的手牌常鸡计数
                if p in receive_set:
                    totals[p] += int(emap.get(p, 0)) * v_map[cname]
    return totals


def settle_hand_chicken_pairwise(pay_set, receive_set, totals) -> List[Transfer]:
    """手牌常鸡互斥结算"""
    transfers = []
    el = sorted(list(pay_set))
    for i in range(len(el)):
        for j in range(i + 1, len(el)):
            a, b = el[i], el[j]
            val_a, val_b = totals.get(a, 0), totals.get(b, 0)
            if val_a > val_b and a in receive_set:
                add_transfer(transfers, a, b, val_a - val_b, "🐔 手牌常鸡互斥")
            elif val_b > val_a and b in receive_set:
                add_transfer(transfers, b, a, val_b - val_a, "🐔 手牌常鸡互斥")
    return transfers


def settle_remaining_bump_kong_items(
        *, players, pay_set, receive_set_actual, common_v, gang_data,
        first_yj_who, first_yj_res, first_yj_tar,
        first_b8_who, first_b8_res, first_b8_tar
) -> List[Transfer]:
    """
    3. 碰/杠剩余常鸡结算 (V25 最终修正版)
    - 计分逻辑双轨制 (碰牌/杠牌 通用)：
        - 对于“责任人”(Victim)：扣除1张 (碰算2张, 杠算3张)。
        - 对于“非责任人”(Bystanders)：全额 (碰算3张, 杠算4张)。
    - 结算对象：全场结算。
    """
    transfers = []
    v_yj = int(common_v.get("幺鸡", 0))
    v_b8 = int(common_v.get("八筒", 0))

    # ---------------- 辅助函数：生成剩余项目 ----------------
    def check_bump_remain(cname, first_who, first_res, first_tar, val):
        if val <= 0: return
        if first_who != "无/未现" and first_res == "被碰" and first_tar:
            has_bu = False
            for g in gang_data:
                if g.get("card") == cname and g.get("type") == "补杠" and g.get("doer") == first_tar:
                    has_bu = True
                    break

            # 只有未升级为补杠时，才结算碰牌剩余
            if not has_bu:
                owner = first_tar
                victim = first_who

                # 双轨制金额
                amt_for_victim = 2 * val  # 3-1
                amt_for_others = 3 * val  # 3

                # 1. 针对责任人 (Victim)
                if victim in pay_set:
                    if owner in receive_set_actual:
                        add_transfer(transfers, owner, victim, amt_for_victim, f"🐔 碰牌剩余-{cname}(2张)")
                    elif owner in pay_set and victim in receive_set_actual:
                        add_transfer(transfers, victim, owner, amt_for_victim, f"未听牌-赔付碰牌剩余-{cname}(2张)")

                # 2. 针对其他人
                bystanders = [p for p in pay_set if p != owner and p != victim]
                for p in bystanders:
                    if owner in receive_set_actual:
                        add_transfer(transfers, owner, p, amt_for_others, f"🐔 碰牌剩余-{cname}(3张)")
                    elif owner in pay_set and p in receive_set_actual:
                        add_transfer(transfers, p, owner, amt_for_others, f"未听牌-赔付碰牌剩余-{cname}(3张)")

    def check_gang_remain(val):
        if val <= 0: return
        for g in gang_data:
            cname = g.get("card")
            gtype = g.get("type")
            owner = g.get("doer")
            victim = g.get("victim")  # 责任人（若有）

            if cname not in ["幺鸡", "八筒"]: continue
            if not owner: continue

            # 1. 确定责任人 (real_victim)
            real_victim = None
            if gtype == "责任明杠":
                real_victim = victim
            elif gtype == "补杠":
                is_resp_origin = False
                if cname == "幺鸡" and first_yj_who != "无/未现" and first_yj_res == "被碰" and first_yj_tar == owner:
                    is_resp_origin = True
                    real_victim = first_yj_who
                elif cname == "八筒" and first_b8_who != "无/未现" and first_b8_res == "被碰" and first_b8_tar == owner:
                    is_resp_origin = True
                    real_victim = first_b8_who

            # 2. 计算金额 (双轨制)
            # 责任人: 3张; 路人: 4张
            amt_for_victim = 3 * int(common_v.get(cname, 0))
            amt_for_others = 4 * int(common_v.get(cname, 0))

            # 3. 执行结算

            # 3.1 针对 责任人 (real_victim)
            if real_victim and real_victim in pay_set:
                if owner in receive_set_actual:
                    add_transfer(transfers, owner, real_victim, amt_for_victim, f"🐔 杠牌剩余-{cname}(3张)")
                elif owner in pay_set and real_victim in receive_set_actual:
                    add_transfer(transfers, real_victim, owner, amt_for_victim, f"未听牌-赔付杠牌剩余-{cname}(3张)")

            # 3.2 针对 其他人 (bystanders)
            bystanders = [p for p in pay_set if p != owner and p != real_victim]
            for p in bystanders:
                if owner in receive_set_actual:
                    add_transfer(transfers, owner, p, amt_for_others, f"🐔 杠牌剩余-{cname}(4张)")
                elif owner in pay_set and p in receive_set_actual:
                    add_transfer(transfers, p, owner, amt_for_others, f"未听牌-赔付杠牌剩余-{cname}(4张)")

    # 执行检测
    check_bump_remain("幺鸡", first_yj_who, first_yj_res, first_yj_tar, v_yj)
    check_bump_remain("八筒", first_b8_who, first_b8_res, first_b8_tar, v_b8)
    check_gang_remain(1)

    return transfers


def settle_not_ready_baopay_v20(
        *, not_ready_set, pay_set, receive_set_actual, common_v,
        first_yj_who, first_yj_res, first_yj_tar,
        first_b8_who, first_b8_res, first_b8_tar,
) -> List[Transfer]:
    """
    V25 未听牌包赔 - 仅剩余项目（责任鸡 & 冲锋鸡）
    """
    transfers = []
    if not not_ready_set: return transfers

    receive_set_hypo = set(receive_set_actual) | set(not_ready_set)

    # 1. 责任鸡反转
    hypo_resp = []
    hypo_resp += settle_common_first_responsibility(pay_set, receive_set_hypo, common_v, "幺鸡", first_yj_who,
                                                    first_yj_res, first_yj_tar)
    hypo_resp += settle_common_first_responsibility(pay_set, receive_set_hypo, common_v, "八筒", first_b8_who,
                                                    first_b8_res, first_b8_tar)

    for tr in hypo_resp:
        if tr.receiver in not_ready_set and tr.payer in receive_set_actual:
            add_transfer(transfers, tr.payer, tr.receiver, tr.amount, f"未听牌-包赔(责任鸡应得翻转): {tr.reason}")

    # 2. 冲锋鸡反转
    hypo_charge = []
    hypo_charge += settle_charge_chicken_pairwise(pay_set, receive_set_hypo, common_v, "幺鸡", first_yj_who,
                                                  first_yj_res)
    hypo_charge += settle_charge_chicken_pairwise(pay_set, receive_set_hypo, common_v, "八筒", first_b8_who,
                                                  first_b8_res)

    for tr in hypo_charge:
        if tr.receiver in not_ready_set and tr.payer in receive_set_actual:
            add_transfer(transfers, tr.payer, tr.receiver, tr.amount, f"未听牌-包赔(冲锋鸡应得翻转): {tr.reason}")

    return transfers


# -------------------------------
# Main calculate (Aggregator) - V25
# -------------------------------
def calculate_all(players, winners, method, loser, hu_shape, is_qing, special_events, rules_config, fan_card,
                  ready_list, first_yj_who, first_yj_res, first_yj_tar, first_b8_who, first_b8_res, first_b8_tar,
                  extra_yj, extra_b8, hand_total_counts, gang_data, common_v, fan_unit=1) -> Tuple[
    Dict[str, int], Dict[str, List[str]]]:
    winners_set = set(winners)
    ready_set = set([p for p in ready_list if p in players])
    eligible_set = set([p for p in players if p in (ready_set | winners_set)])

    burn_trigger = (method == "点炮") and (("热炮" in special_events) or ("抢杠胡" in special_events))
    burn_player = loser if burn_trigger else None
    burn_player_is_ready = False
    if burn_player and (burn_player in ready_set): burn_player_is_ready = True

    not_ready_set = set([p for p in players if p not in eligible_set])

    validate_objective_facts(
        players=players,
        fan_card=fan_card,
        hand_total_counts={p: int(hand_total_counts.get(p, 0)) for p in players},
        first_yj_who=first_yj_who, first_yj_res=first_yj_res, first_yj_tar=first_yj_tar,
        first_b8_who=first_b8_who, first_b8_res=first_b8_res, first_b8_tar=first_b8_tar,
        extra_yj=extra_yj,
        extra_b8=extra_b8,
        gang_data=gang_data,
    )

    validate_winner_and_event_consistency(
        players=players,
        winners=winners,
        method=method,
        first_yj_who=first_yj_who, first_yj_res=first_yj_res, first_yj_tar=first_yj_tar,
        first_b8_who=first_b8_who, first_b8_res=first_b8_res, first_b8_tar=first_b8_tar,
        gang_data=gang_data,
    )

    burn_ready_player = burn_player if (burn_trigger and burn_player and burn_player_is_ready) else None
    receive_set = set(eligible_set)
    if burn_ready_player: receive_set.discard(burn_ready_player)

    pay_set = set(receive_set) | set(not_ready_set)
    if burn_ready_player: pay_set.add(burn_ready_player)

    transfers = []

    # 1. 胡牌
    if winners:
        transfers += settle_hu(players, winners, method, loser, hu_shape, is_qing, special_events, rules_config)

    # 2. 翻鸡 (独立互斥)
    transfers += settle_fan_chicken_pairwise(pay_set, receive_set,
                                             {p: int(hand_total_counts.get(p, 0)) for p in players}, unit=int(fan_unit))

    # 3. 杠牌基础分 (Action Score) - 全场支付
    gp = set(eligible_set)
    if burn_ready_player: gp.discard(burn_ready_player)
    transfers += settle_gang_base_points(gang_data, gp, burn_ready_player, not_ready_set)

    # 4. 责任鸡 (1张，双倍)
    transfers += settle_common_first_responsibility(pay_set, receive_set, common_v, "幺鸡", first_yj_who, first_yj_res,
                                                    first_yj_tar)
    transfers += settle_common_first_responsibility(pay_set, receive_set, common_v, "八筒", first_b8_who, first_b8_res,
                                                    first_b8_tar)

    # 5. 手牌常鸡 (纯手牌互斥)
    hand_totals = build_hand_chicken_totals(players, receive_set, common_v, extra_yj, extra_b8)
    transfers += settle_hand_chicken_pairwise(pay_set, receive_set, hand_totals)

    # 6. 碰/杠 剩余常鸡 (双轨制计分) - 🚨 V25 修复：碰牌也适用双轨制
    transfers += settle_remaining_bump_kong_items(
        players=players, pay_set=pay_set, receive_set_actual=receive_set, common_v=common_v, gang_data=gang_data,
        first_yj_who=first_yj_who, first_yj_res=first_yj_res, first_yj_tar=first_yj_tar,
        first_b8_who=first_b8_who, first_b8_res=first_b8_res, first_b8_tar=first_b8_tar
    )

    # 7. 冲锋鸡 (互斥)
    transfers += settle_charge_chicken_pairwise(pay_set, receive_set, common_v, "幺鸡", first_yj_who, first_yj_res)
    transfers += settle_charge_chicken_pairwise(pay_set, receive_set, common_v, "八筒", first_b8_who, first_b8_res)

    # 8. 未听牌包赔 (仅处理 责任鸡 & 冲锋鸡 的反转)
    transfers += settle_not_ready_baopay_v20(
        not_ready_set=not_ready_set, pay_set=pay_set, receive_set_actual=receive_set, common_v=common_v,
        first_yj_who=first_yj_who, first_yj_res=first_yj_res, first_yj_tar=first_yj_tar,
        first_b8_who=first_b8_who, first_b8_res=first_b8_res, first_b8_tar=first_b8_tar
    )

    scores = {p: 0 for p in players}
    details = {p: [] for p in players}
    for tr in transfers:
        if tr.receiver in players and tr.payer in players:
            scores[tr.receiver] += tr.amount
            scores[tr.payer] -= tr.amount
            details[tr.receiver].append(f"{tr.reason}: +{int(tr.amount)}（{tr.payer}付）")
            details[tr.payer].append(f"{tr.reason}: -{int(tr.amount)}（付给{tr.receiver}）")
    return scores, details


# ==============================================================================
# UI - V25 Ultimate Stable
# ==============================================================================

def main():
    st.set_page_config(page_title="捉鸡Pro - V25", page_icon="🀄", layout="wide")

    main_round = int(st.session_state.get("main_round", 0))
    K = lambda s: f"main_{main_round}_{s}"

    # ---------------- UI helpers (visual only) ----------------
    def ui_section(title: str, icon: str = "", caption: Optional[str] = None):
        cap_html = f'<span class="glass-caption">{caption}</span>' if caption else ""
        st.markdown(
            f'<div class="glass-header"><span class="glass-header-icon">{icon}</span> {title}{cap_html}</div>',
            unsafe_allow_html=True,
        )

    def ui_divider(label: Optional[str] = None):
        if label:
            st.markdown(f'<div class="ui-divider"><span>{label}</span></div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="ui-divider" style="margin-top:10px;"></div>', unsafe_allow_html=True)

    if "gang_rows" not in st.session_state:
        st.session_state.gang_rows = 1

    # ---------------- Sidebar ----------------
    with st.sidebar:
        st.header("⚙️ 全局设定")

        if "p_names" not in st.session_state:
            st.session_state.p_names = ["玩家A", "玩家B", "玩家C", "玩家D"]

        with st.expander("👥 玩家署名", expanded=True):
            new_names = []
            for i, n in enumerate(st.session_state.p_names):
                new_names.append(st.text_input(f"座位 {i + 1}", n, key=f"pn_{i}"))
            st.session_state.p_names = new_names

        players = st.session_state.p_names
        if len(set(players)) != len(players):
            st.error("名字冲突！请修改。")
            st.stop()

        st.subheader("🔧 规则分值")
        rules_config: Dict[str, int] = {}
        with st.expander("牌型与事件分", expanded=False):
            c_r1, c_r2 = st.columns(2)
            rules_config["平胡"] = c_r1.number_input("平胡", value=5, step=1)
            rules_config["大对子"] = c_r2.number_input("大对子", value=15, step=1)
            rules_config["七对"] = c_r1.number_input("七对", value=25, step=1)
            rules_config["龙七对"] = c_r2.number_input("龙七对", value=50, step=1)
            rules_config["清一色加成"] = st.number_input("清一色加分", value=25, step=5)
            st.write("---")
            default_events = {"报听胡": 25, "杀报": 50, "杠上花": 25, "抢杠胡": 25, "热炮": 25, "天胡": 75, "地胡": 50}
            for k, v in default_events.items():
                rules_config[k] = st.number_input(f"{k}", value=v, step=5)

        with st.expander("🐔 常鸡价值定义", expanded=False):
            c1, c2 = st.columns(2)
            with c1:
                st.caption("🦆 幺鸡 (1条)")
                base_yj = st.number_input("基础值 (1条)", value=2, min_value=0)
                mul_yj = st.number_input("倍数 (1条)", value=1, min_value=1)
            with c2:
                st.caption("🎱 八筒 (8筒)")
                base_b8 = st.number_input("基础值 (8筒)", value=2, min_value=0)
                mul_b8 = st.number_input("倍数 (8筒)", value=1, min_value=1)
            st.caption("注: 翻到9条/7筒时，对应常鸡价值会自动翻倍。")

        with st.expander("🖐️ 翻鸡单位", expanded=False):
            fan_unit = st.number_input("互斥基础分 (Unit)", value=1, min_value=0)

    # ================== CSS INJECTION (SAFE MODE) ==================
    st.markdown("""
        <style>
        /* =============================
           iOS 26-ish Liquid Glass UI
           (Streamlit-safe, no transforms)
           ============================= */

        :root {
            /* App background */
            --bg-0: #05070b;
            --bg-1: #07111b;
            --bg-2: #0b1f2e;

            /* Glass surfaces */
            --glass-strong: rgba(22, 27, 38, 0.72);
            --glass: rgba(22, 27, 38, 0.55);
            --glass-soft: rgba(22, 27, 38, 0.38);

            /* Borders / separators */
            --hairline: rgba(255, 255, 255, 0.16);
            --hairline-2: rgba(255, 255, 255, 0.10);

            /* Text */
            --text: rgba(255,255,255,0.96);
            --text-dim: rgba(255,255,255,0.74);
            --text-faint: rgba(255,255,255,0.56);

            /* Accent (vibrant iOS-like) */
            --accent: rgba(46, 217, 255, 0.95);
            --accent-2: rgba(132, 103, 255, 0.95);
            --accent-3: rgba(0, 245, 152, 0.95);

            /* Shadows */
            --shadow-1: 0 14px 40px rgba(0,0,0,0.35);
            --shadow-2: 0 8px 22px rgba(0,0,0,0.28);

            /* Radii */
            --r-xl: 22px;
            --r-lg: 18px;
            --r-md: 14px;
            --r-sm: 12px;

            /* Blur */
            --blur-strong: blur(22px) saturate(135%);
            --blur: blur(16px) saturate(128%);
            --blur-soft: blur(12px) saturate(120%);
        }

        /* App background: deep space + soft aurora highlights */
        .stApp {
            background:
              radial-gradient(900px 480px at 18% 12%, rgba(46, 217, 255, 0.22), rgba(0,0,0,0) 60%),
              radial-gradient(760px 520px at 82% 16%, rgba(132, 103, 255, 0.20), rgba(0,0,0,0) 58%),
              radial-gradient(880px 520px at 52% 92%, rgba(0, 245, 152, 0.14), rgba(0,0,0,0) 62%),
              linear-gradient(140deg, var(--bg-0), var(--bg-1) 35%, var(--bg-2));
            background-attachment: fixed;
        }

        /* Typography: clean, iOS-like */
        html, body, [class*="css"], .stMarkdown, .stText, .stCaption, label {
            color: var(--text) !important;
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", Arial, sans-serif;
            letter-spacing: 0.1px;
        }

        /* Remove default separators noise */
        hr { display: none !important; }
        footer { visibility: hidden; }

        /* Sidebar as glass sheet */
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, rgba(18, 22, 32, 0.78), rgba(18, 22, 32, 0.62)) !important;
            border-right: 1px solid var(--hairline-2) !important;
            box-shadow: 10px 0 40px rgba(0,0,0,0.25);
            backdrop-filter: var(--blur-strong);
            -webkit-backdrop-filter: var(--blur-strong);
        }
        [data-testid="stSidebar"] * {
            color: var(--text) !important;
        }

        /* Primary content container spacing (more iOS padding) */
        .main .block-container {
            padding-top: 1.35rem;
            padding-bottom: 2.2rem;
            max-width: 1200px;
        }

        /* Glass cards: Streamlit container border wrapper */
        [data-testid="stVerticalBlockBorderWrapper"] {
            position: relative;
            background: linear-gradient(180deg, var(--glass-strong), var(--glass)) !important;
            border: 1px solid var(--hairline) !important;
            border-radius: var(--r-xl) !important;
            padding: 18px 18px 16px 18px !important;
            margin-bottom: 16px !important;
            box-shadow: var(--shadow-2);
            backdrop-filter: var(--blur);
            -webkit-backdrop-filter: var(--blur);
            overflow: hidden;
        }

        /* Card inner sheen (liquid highlight) */
        [data-testid="stVerticalBlockBorderWrapper"]::before {
            content: "";
            position: absolute;
            inset: -2px;
            background:
              radial-gradient(520px 120px at 24% 8%, rgba(255,255,255,0.14), rgba(255,255,255,0) 60%),
              radial-gradient(480px 140px at 82% 18%, rgba(255,255,255,0.10), rgba(255,255,255,0) 62%),
              linear-gradient(180deg, rgba(255,255,255,0.06), rgba(255,255,255,0.00) 28%);
            pointer-events: none;
        }

        /* Headings styling (vibrant but readable) */
        h1 {
            font-weight: 900 !important;
            font-size: 2.0rem !important;
            line-height: 1.15;
            margin-bottom: 0.25rem;
        }
        h2, h3 {
            font-weight: 800 !important;
        }

        /* Existing header class: upgrade to iOS “vibrancy” text */
        .glass-header {
            font-size: 1.25rem;
            font-weight: 900;
            color: var(--text);
            margin-bottom: 0.85rem;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .glass-header-icon {
            font-size: 1.45rem;
            filter: drop-shadow(0 6px 16px rgba(0,0,0,0.35));
        }
        .glass-caption {
            font-size: 0.82rem;
            color: var(--text-dim) !important;
            margin-left: auto;
            font-weight: 650;
            padding: 4px 10px;
            border-radius: 999px;
            background: rgba(255,255,255,0.08);
            border: 1px solid var(--hairline-2);
            backdrop-filter: var(--blur-soft);
            -webkit-backdrop-filter: var(--blur-soft);
        }

        /* Inputs as frosted fields */
        [data-testid="stNumberInput"] input,
        [data-testid="stTextInput"] input,
        [data-testid="stSelectbox"] div[role="combobox"],
        [data-testid="stMultiSelect"] div[role="combobox"] {
            background: rgba(255,255,255,0.08) !important;
            color: var(--text) !important;
            border: 1px solid rgba(255,255,255,0.14) !important;
            border-radius: 14px !important;
            backdrop-filter: var(--blur-soft);
            -webkit-backdrop-filter: var(--blur-soft);
            box-shadow: 0 8px 20px rgba(0,0,0,0.20);
        }

        /* Number input alignment */
        [data-testid="stNumberInput"] input {
            text-align: center;
            font-weight: 750;
        }

        /* Radio / checkbox as pill glass */
        [data-testid="stRadio"] div[role="radiogroup"],
        [data-testid="stCheckbox"] {
            border-radius: 16px;
        }

        /* Buttons: iOS glass capsules */
        .stButton > button {
            border-radius: 999px !important;
            border: 1px solid rgba(255,255,255,0.16) !important;
            background: linear-gradient(180deg, rgba(255,255,255,0.16), rgba(255,255,255,0.08)) !important;
            color: var(--text) !important;
            font-weight: 850 !important;
            letter-spacing: 0.2px;
            padding: 0.72rem 1.05rem !important;
            box-shadow: var(--shadow-2);
            backdrop-filter: var(--blur);
            -webkit-backdrop-filter: var(--blur);
        }
        .stButton > button:hover {
            border-color: rgba(255,255,255,0.24) !important;
            background: linear-gradient(180deg, rgba(255,255,255,0.22), rgba(255,255,255,0.10)) !important;
        }
        .stButton > button:active {
            background: linear-gradient(180deg, rgba(255,255,255,0.12), rgba(255,255,255,0.06)) !important;
        }

        /* Primary button: subtle accent glow (no animation) */
        .stButton > button[kind="primary"],
        div[data-testid="stButton"] > button[kind="primary"] {
            border: 1px solid rgba(46, 217, 255, 0.30) !important;
            background:
              radial-gradient(520px 160px at 30% 20%, rgba(46, 217, 255, 0.22), rgba(0,0,0,0) 55%),
              radial-gradient(520px 180px at 78% 30%, rgba(132, 103, 255, 0.18), rgba(0,0,0,0) 60%),
              linear-gradient(180deg, rgba(255,255,255,0.18), rgba(255,255,255,0.08)) !important;
            box-shadow: 0 14px 44px rgba(0,0,0,0.34), 0 0 0 1px rgba(46,217,255,0.12);
        }

        /* Expanders: glass panel */
        details, [data-testid="stExpander"] {
            border-radius: var(--r-lg) !important;
        }
        [data-testid="stExpander"] > details {
            background: rgba(255,255,255,0.06) !important;
            border: 1px solid rgba(255,255,255,0.12) !important;
            border-radius: var(--r-lg) !important;
            box-shadow: 0 10px 26px rgba(0,0,0,0.20);
            backdrop-filter: var(--blur-soft);
            -webkit-backdrop-filter: var(--blur-soft);
            overflow: hidden;
        }

        /* Metrics (result tiles) */
        [data-testid="stMetric"] {
            background: rgba(255,255,255,0.06) !important;
            border: 1px solid rgba(255,255,255,0.12) !important;
            border-radius: 18px !important;
            padding: 12px 14px !important;
            backdrop-filter: var(--blur-soft);
            -webkit-backdrop-filter: var(--blur-soft);
            box-shadow: 0 10px 26px rgba(0,0,0,0.20);
        }

        /* Your custom “ticket” list: make it more iOS glass */
        .holo-ticket {
            padding: 12px 16px;
            margin-bottom: 10px;
            border-radius: 18px;
            background:
              radial-gradient(420px 140px at 18% 20%, rgba(255,255,255,0.14), rgba(255,255,255,0) 60%),
              linear-gradient(180deg, rgba(255,255,255,0.12), rgba(255,255,255,0.06));
            border: 1px solid rgba(255,255,255,0.14);
            box-shadow: 0 10px 26px rgba(0,0,0,0.24);
            backdrop-filter: var(--blur);
            -webkit-backdrop-filter: var(--blur);
        }
        .tx-arrow { color: var(--text-faint); font-size: 0.85rem; }
        .tx-pay, .tx-get { text-shadow: 0 8px 20px rgba(0,0,0,0.35); }
        .tx-amt-box { text-shadow: 0 10px 26px rgba(0,0,0,0.35); }

        /* Alerts: soften */
        [data-testid="stAlert"] {
            border-radius: 18px !important;
            border: 1px solid rgba(255,255,255,0.14) !important;
            background: rgba(255,255,255,0.06) !important;
            backdrop-filter: var(--blur-soft);
            -webkit-backdrop-filter: var(--blur-soft);
        }

        /* Mobile tweaks */
        @media (max-width: 768px) {
            .main .block-container { padding-left: 0.8rem; padding-right: 0.8rem; }
            h1 { font-size: 1.65rem !important; }
            .glass-header { font-size: 1.12rem; }
            [data-testid="stNumberInput"] input { font-size: 16px; }
        }
        /* ===== iOS Chrome compatibility + UX polish ===== */

        /* Soft grain overlay (helps Liquid Glass feel even when blur is weak) */
        .stApp::after {
            content: "";
            position: fixed;
            inset: 0;
            pointer-events: none;
            background:
              radial-gradient(1px 1px at 18% 22%, rgba(255,255,255,0.035) 50%, rgba(0,0,0,0) 52%),
              radial-gradient(1px 1px at 62% 48%, rgba(255,255,255,0.030) 50%, rgba(0,0,0,0) 52%),
              radial-gradient(1px 1px at 78% 74%, rgba(255,255,255,0.028) 50%, rgba(0,0,0,0) 52%);
            background-size: 160px 160px;
            opacity: 0.55;
            mix-blend-mode: overlay;
        }

        /* Stickies */
        .sticky-panel {
            position: sticky;
            top: 14px;
            z-index: 5;
        }

        /* Pill chips */
        .chip {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 6px 10px;
            border-radius: 999px;
            background: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.14);
            color: var(--text-dim);
            font-size: 0.82rem;
            font-weight: 700;
            backdrop-filter: var(--blur-soft);
            -webkit-backdrop-filter: var(--blur-soft);
        }

        /* Sticky action bar */
        .action-bar {
            position: sticky;
            top: 10px;
            z-index: 6;
            background: linear-gradient(180deg, rgba(18,22,32,0.72), rgba(18,22,32,0.45));
            border: 1px solid rgba(255,255,255,0.14);
            border-radius: 20px;
            padding: 12px 12px 10px 12px;
            box-shadow: var(--shadow-2);
            backdrop-filter: var(--blur-strong);
            -webkit-backdrop-filter: var(--blur-strong);
            overflow: hidden;
            margin-bottom: 14px;
        }
        .action-bar::before {
            content: "";
            position: absolute;
            inset: -2px;
            pointer-events: none;
            background:
              radial-gradient(520px 140px at 18% 10%, rgba(255,255,255,0.14), rgba(255,255,255,0) 58%),
              linear-gradient(180deg, rgba(255,255,255,0.06), rgba(255,255,255,0.00) 32%);
        }

        /* Improve focus ring (touch UX) */
        button:focus, input:focus, [role="combobox"]:focus {
            outline: none !important;
            box-shadow: 0 0 0 2px rgba(46, 217, 255, 0.18), 0 10px 26px rgba(0,0,0,0.24) !important;
        }

        /* Dropdown menu surface */
        [data-baseweb="popover"] > div {
            background: rgba(18, 22, 32, 0.86) !important;
            border: 1px solid rgba(255,255,255,0.14) !important;
            backdrop-filter: var(--blur-strong);
            -webkit-backdrop-filter: var(--blur-strong);
            border-radius: 16px !important;
            box-shadow: 0 18px 46px rgba(0,0,0,0.45) !important;
        }

        /* Scrollbar subtle */
        ::-webkit-scrollbar { width: 10px; height: 10px; }
        ::-webkit-scrollbar-thumb {
            background: rgba(255,255,255,0.14);
            border: 2px solid rgba(0,0,0,0);
            background-clip: padding-box;
            border-radius: 999px;
        }
        ::-webkit-scrollbar-track { background: rgba(0,0,0,0.0); }

        /* Reduce heavy effects if user prefers */
        @media (prefers-reduced-transparency: reduce) {
            [data-testid="stVerticalBlockBorderWrapper"],
            [data-testid="stSidebar"],
            .action-bar {
                backdrop-filter: none !important;
                -webkit-backdrop-filter: none !important;
            }
            .stApp::after { opacity: 0.25; }
        }

        /* =============================
           Light Mode (iOS-like Frost)
           - Only applies when the OS/browser is in light color scheme
           - Does NOT affect dark mode
           ============================= */
        @media (prefers-color-scheme: light) {
            :root {
                --bg-0: #f6f8fb;
                --bg-1: #eef3f8;
                --bg-2: #e8f0f7;

                --glass-strong: rgba(255, 255, 255, 0.72);
                --glass: rgba(255, 255, 255, 0.58);
                --glass-soft: rgba(255, 255, 255, 0.42);

                --hairline: rgba(10, 20, 35, 0.12);
                --hairline-2: rgba(10, 20, 35, 0.08);

                --text: rgba(10, 18, 32, 0.92);
                --text-dim: rgba(10, 18, 32, 0.68);
                --text-faint: rgba(10, 18, 32, 0.52);

                /* Slightly deeper accents for light backgrounds */
                --accent: rgba(0, 122, 255, 0.92);
                --accent-2: rgba(88, 86, 214, 0.90);
                --accent-3: rgba(52, 199, 89, 0.90);

                --shadow-1: 0 16px 46px rgba(15, 25, 40, 0.14);
                --shadow-2: 0 10px 26px rgba(15, 25, 40, 0.12);

                --blur-strong: blur(22px) saturate(130%);
                --blur: blur(16px) saturate(125%);
                --blur-soft: blur(12px) saturate(120%);
            }

            /* App background: light frost + subtle aurora */
            .stApp {
                background:
                  radial-gradient(860px 520px at 16% 10%, rgba(0, 122, 255, 0.12), rgba(0,0,0,0) 62%),
                  radial-gradient(760px 520px at 84% 16%, rgba(88, 86, 214, 0.10), rgba(0,0,0,0) 62%),
                  radial-gradient(920px 560px at 56% 92%, rgba(52, 199, 89, 0.08), rgba(0,0,0,0) 66%),
                  linear-gradient(140deg, var(--bg-0), var(--bg-1) 38%, var(--bg-2));
                background-attachment: fixed;
            }

            /* Typography colors in light mode */
            html, body, [class*="css"], .stMarkdown, .stText, .stCaption, label {
                color: var(--text) !important;
            }

            /* Sidebar: light glass sheet */
            [data-testid="stSidebar"] {
                background: linear-gradient(180deg, rgba(255,255,255,0.82), rgba(255,255,255,0.66)) !important;
                border-right: 1px solid var(--hairline-2) !important;
                box-shadow: 10px 0 40px rgba(15,25,40,0.10);
                backdrop-filter: var(--blur-strong);
                -webkit-backdrop-filter: var(--blur-strong);
            }
            [data-testid="stSidebar"] * {
                color: var(--text) !important;
            }

            /* Cards: brighter frost, slightly stronger border */
            [data-testid="stVerticalBlockBorderWrapper"] {
                background: linear-gradient(180deg, var(--glass-strong), var(--glass)) !important;
                border: 1px solid var(--hairline) !important;
                box-shadow: var(--shadow-2);
            }
            [data-testid="stVerticalBlockBorderWrapper"]::before {
                background:
                  radial-gradient(520px 120px at 24% 8%, rgba(255,255,255,0.55), rgba(255,255,255,0) 60%),
                  radial-gradient(480px 140px at 82% 18%, rgba(255,255,255,0.40), rgba(255,255,255,0) 62%),
                  linear-gradient(180deg, rgba(255,255,255,0.26), rgba(255,255,255,0.00) 28%);
            }

            /* Inputs: light frosted fields */
            [data-testid="stNumberInput"] input,
            [data-testid="stTextInput"] input,
            [data-testid="stSelectbox"] div[role="combobox"],
            [data-testid="stMultiSelect"] div[role="combobox"] {
                background: rgba(255,255,255,0.72) !important;
                color: var(--text) !important;
                border: 1px solid rgba(10, 20, 35, 0.14) !important;
                box-shadow: 0 10px 22px rgba(15,25,40,0.10);
            }

            /* Buttons: light glass capsules */
            .stButton > button {
                border: 1px solid rgba(10, 20, 35, 0.14) !important;
                background: linear-gradient(180deg, rgba(255,255,255,0.92), rgba(255,255,255,0.70)) !important;
                color: var(--text) !important;
                box-shadow: 0 12px 24px rgba(15,25,40,0.12);
            }
            .stButton > button:hover {
                border-color: rgba(10, 20, 35, 0.20) !important;
                background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(255,255,255,0.76)) !important;
            }
            .stButton > button[kind="primary"],
            div[data-testid="stButton"] > button[kind="primary"] {
                border: 1px solid rgba(0, 122, 255, 0.28) !important;
                background:
                  radial-gradient(520px 160px at 30% 20%, rgba(0, 122, 255, 0.14), rgba(0,0,0,0) 58%),
                  radial-gradient(520px 180px at 78% 30%, rgba(88, 86, 214, 0.10), rgba(0,0,0,0) 62%),
                  linear-gradient(180deg, rgba(255,255,255,0.94), rgba(255,255,255,0.68)) !important;
                box-shadow: 0 16px 34px rgba(15,25,40,0.14), 0 0 0 1px rgba(0,122,255,0.10);
            }

            /* Chips + action bar: light vibrancy */
            .chip {
                background: rgba(255,255,255,0.72);
                border: 1px solid rgba(10,20,35,0.12);
                color: var(--text-dim);
            }
            .action-bar {
                background: linear-gradient(180deg, rgba(255,255,255,0.78), rgba(255,255,255,0.58));
                border: 1px solid rgba(10,20,35,0.12);
                box-shadow: 0 14px 34px rgba(15,25,40,0.12);
            }

            /* Dropdown menu surface: light */
            [data-baseweb="popover"] > div {
                background: rgba(255,255,255,0.92) !important;
                border: 1px solid rgba(10,20,35,0.12) !important;
                box-shadow: 0 18px 46px rgba(15,25,40,0.18) !important;
            }

            /* Tickets: light glass */
            .holo-ticket {
                background:
                  radial-gradient(420px 140px at 18% 20%, rgba(255,255,255,0.70), rgba(255,255,255,0) 62%),
                  linear-gradient(180deg, rgba(255,255,255,0.88), rgba(255,255,255,0.62));
                border: 1px solid rgba(10,20,35,0.12);
                box-shadow: 0 12px 26px rgba(15,25,40,0.12);
            }

            /* Grain: dial down for light backgrounds */
            .stApp::after {
                opacity: 0.28;
                mix-blend-mode: multiply;
            }

            /* Focus ring: more visible in light mode */
            button:focus, input:focus, [role="combobox"]:focus {
                box-shadow: 0 0 0 2px rgba(0, 122, 255, 0.18), 0 10px 26px rgba(15,25,40,0.12) !important;
            }
        }
        /* UI dividers */
        .ui-divider {
            position: relative;
            height: 1px;
            background: rgba(255,255,255,0.10);
            margin: 12px 0 12px 0;
            border-radius: 999px;
        }
        .ui-divider > span {
            position: absolute;
            top: -11px;
            left: 50%;
            transform: translateX(-50%);
            padding: 2px 10px;
            border-radius: 999px;
            background: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.12);
            font-size: 0.78rem;
            font-weight: 750;
            color: var(--text-dim);
            backdrop-filter: var(--blur-soft);
            -webkit-backdrop-filter: var(--blur-soft);
        }

        /* Chip status variants */
        .chip.ok { border-color: rgba(0,245,152,0.35); box-shadow: 0 0 0 1px rgba(0,245,152,0.10); }
        .chip.warn { border-color: rgba(255,214,10,0.35); box-shadow: 0 0 0 1px rgba(255,214,10,0.10); }
        .chip.bad { border-color: rgba(255,69,58,0.35); box-shadow: 0 0 0 1px rgba(255,69,58,0.10); }

        /* Title subtitle */
        .hero-sub {
            margin-top: -6px;
            margin-bottom: 12px;
            color: var(--text-dim);
            font-weight: 650;
            font-size: 0.92rem;
        }

        /* Make expander summary a bit bolder */
        details > summary {
            font-weight: 800 !important;
        }
        </style>
    """, unsafe_allow_html=True)

    # ---------------- UI Content ----------------
    st.title("🀄 捉鸡Pro 智能结算终端")
    st.markdown('<div class="hero-sub">更清晰的录入结构｜更少误操作｜结算结果一眼可读</div>', unsafe_allow_html=True)

    left, right = st.columns([1.25, 0.85], gap="large")

    # --- Left column: all input UI blocks ---
    with left:
        # Match Info
        with st.container(border=True):
            ui_section("本局胜负", icon="🏆")

            is_fan = st.checkbox("本局有翻牌?", value=True, key=K("is_fan"))
            fan_card = ""
            if is_fan:
                c_f1, c_f2 = st.columns(2)
                f_num = c_f1.selectbox("点数", range(1, 10), key=K("fn"), label_visibility="collapsed")
                f_suit = c_f2.selectbox("花色", ["筒", "条", "万"], key=K("fs"), label_visibility="collapsed")
                fan_card = f"{f_num}{f_suit}"
            else:
                st.caption("无翻牌")

            winners: List[str] = []
            method = "自摸"
            loser = None
            hu_shape = "平胡"
            is_qing = False
            special_events: List[str] = []

            st.write("")
            c_w1, c_w2 = st.columns([3, 2])
            with c_w1:
                winners = st.multiselect("🎉 胡牌者", players, key=K("winners"), placeholder="选择胡牌玩家")
            with c_w2:
                method = st.radio("方式", ["自摸", "点炮"], horizontal=True, key=K("method"),
                                  label_visibility="collapsed")

            if method == "自摸" and len(winners) > 1:
                st.error("自摸仅允许 1 位胡牌者。")
            elif method == "点炮":
                loser_candidates = [p for p in players if p not in set(winners)]
                if loser_candidates:
                    loser = st.selectbox("💥 点炮者", loser_candidates, key=K("loser"))
                elif winners:
                    st.error("除胡牌者外无其他人可选为点炮者。")

            if winners:
                with st.expander("📋 胡牌详情 & 特殊事件", expanded=True):
                    c_d1, c_d2 = st.columns([1, 2])
                    with c_d1:
                        hu_shape = st.selectbox("牌型", ["平胡", "大对子", "七对", "龙七对"], key=K("hu_shape"))
                        is_qing = st.checkbox("清一色", key=K("is_qing"))
                    with c_d2:
                        all_events = ["报听胡", "杀报", "杠上花", "热炮", "抢杠胡", "天胡", "地胡"]
                        cand = [e for e in all_events if
                                e not in ["热炮", "抢杠胡"]] if method == "自摸" else all_events
                        special_events = st.multiselect("特殊事件", cand, key=K("special_events"))

        # Ready
        with st.container(border=True):
            ui_section("听牌状态 (叫嘴)", icon="👂")
            ready_list = st.multiselect("已听牌玩家", players, default=players, key=K("ready_list"))

        # Common Chicken
        common_v = build_common_chicken_cfg(base_yj, mul_yj, base_b8, mul_b8, fan_card)
        with st.container(border=True):
            ui_section("首出常鸡", icon="🚀", caption=f"1条{common_v['幺鸡']}/8筒{common_v['八筒']}")

            # Auto-disable mutual '被胡' (UI-only enforcement)
            key_fyr = K("fyr")
            key_fbr = K("fbr")
            if st.session_state.get(key_fyr) == "被胡" and st.session_state.get(key_fbr) == "被胡":
                st.session_state[key_fbr] = "安全"

            if method == "自摸":
                if st.session_state.get(key_fyr) == "被胡":
                    st.session_state[key_fyr] = "安全"
                if st.session_state.get(key_fbr) == "被胡":
                    st.session_state[key_fbr] = "安全"

            col_yw, col_yr, col_bw, col_br = st.columns([1.5, 2, 1.5, 2])

            # ---------- 幺鸡 ----------
            with col_yw:
                st.caption("**🦆 幺鸡 (1条) 首出**")
                fyw = st.selectbox("首出", ["无/未现"] + players, key=K("fyw"), label_visibility="collapsed")

            fyr = "安全"
            fyt = None
            with col_yr:
                if fyw != "无/未现":
                    yj_opts = ["安全", "被碰", "被明杠", "被胡"]
                    if method == "自摸":
                        yj_opts = ["安全", "被碰", "被明杠"]
                        if st.session_state.get(K("fyr")) == "被胡": st.session_state[K("fyr")] = "安全"
                    if st.session_state.get(K("fbr")) == "被胡":
                        yj_opts = ["安全", "被碰", "被明杠"]
                        if st.session_state.get(K("fyr")) == "被胡": st.session_state[K("fyr")] = "安全"

                    fyr = st.radio("结局", yj_opts, horizontal=True, key=K("fyr"), label_visibility="collapsed")
                    if fyr != "安全":
                        if fyr == "被胡":
                            fyt = [w for w in winners if w in players]
                            st.caption(f"🧩 被胡目标自动继承胡牌者：{'、'.join(fyt) if fyt else '（未选胡牌者）'}")
                        else:
                            fyt = st.selectbox("被谁?", [p for p in players if p != fyw], key=K("fyt"))

            # ---------- 八筒 ----------
            with col_bw:
                st.caption("**🎱 八筒 (8筒) 首出**")
                fbw = st.selectbox("首出", ["无/未现"] + players, key=K("fbw"), label_visibility="collapsed")

            fbr = "安全"
            fbt = None
            with col_br:
                if fbw != "无/未现":
                    b8_opts = ["安全", "被碰", "被明杠", "被胡"]
                    if method == "自摸":
                        b8_opts = ["安全", "被碰", "被明杠"]
                        if st.session_state.get(K("fbr")) == "被胡": st.session_state[K("fbr")] = "安全"
                    if st.session_state.get(K("fyr")) == "被胡":
                        b8_opts = ["安全", "被碰", "被明杠"]
                        if st.session_state.get(K("fbr")) == "被胡": st.session_state[K("fbr")] = "安全"

                    fbr = st.radio("结局", b8_opts, horizontal=True, key=K("fbr"), label_visibility="collapsed")
                    if fbr != "安全":
                        if fbr == "被胡":
                            fbt = [w for w in winners if w in players]
                            st.caption(f"🧩 被胡目标自动继承胡牌者：{'、'.join(fbt) if fbt else '（未选胡牌者）'}")
                        else:
                            fbt = st.selectbox("被谁?", [p for p in players if p != fbw], key=K("fbt"))

        with st.container(border=True):
            ui_section("手牌常鸡", icon="🔢")
            extra_yj, extra_b8 = {}, {}
            cols_p = st.columns(4)
            for i, p in enumerate(players):
                with cols_p[i]:
                    st.subheader(p)
                    # ✅ 修复：添加 step=1 找回加减按钮
                    extra_yj[p] = st.number_input(f"🦆({p})", 0, 4, 0, step=1, key=K(f"ey_{i}"))
                    extra_b8[p] = st.number_input(f"🎱({p})", 0, 4, 0, step=1, key=K(f"eb_{i}"))

        # Fan & Gang
        c_fan, c_gang = st.columns([1, 1.5])
        with c_fan:
            with st.container(border=True):
                ui_section("翻鸡", icon="🖐️")
                hand_total_counts = {}
                if fan_card in ["9条", "7筒"]:
                    st.info("翻倍鸡不互斥")
                else:
                    for i, p in enumerate(players):
                        hand_total_counts[p] = st.number_input(f"{p}数", 0, 4, 0, key=K(f"fc_{i}"))
        with c_gang:
            with st.container(border=True):
                ui_section("杠牌登记", icon="🛠️")
                gang_data = []

                if fyw != "无/未现" and fyr == "被明杠" and fyt:
                    gang_data.append({'doer': fyt, 'type': '责任明杠', 'card': '幺鸡', 'victim': fyw})
                    st.caption(f"ℹ️ 自动添加: {fyt} 责任明杠 {fyw} (幺鸡)")
                if fbw != "无/未现" and fbr == "被明杠" and fbt:
                    gang_data.append({'doer': fbt, 'type': '责任明杠', 'card': '八筒', 'victim': fbw})
                    st.caption(f"ℹ️ 自动添加: {fbt} 责任明杠 {fbw} (八筒)")

                for i in range(st.session_state.gang_rows):
                    c_g1, c_g2, c_g3, c_g4 = st.columns([1.2, 1, 1, 1.2])
                    gw = c_g1.selectbox("杠主", ["无"] + players, key=K(f"gw{i}"), label_visibility="collapsed",
                                        placeholder="杠主")
                    if gw != "无":
                        gt = c_g2.selectbox("类型", ["暗杠", "补杠", "普通明杠"], key=K(f"gt{i}"),
                                            label_visibility="collapsed")
                        if gt == "补杠":
                            gc = c_g3.selectbox("牌种", ["杂牌"], key=K(f"gc{i}"), label_visibility="collapsed",
                                                disabled=True)
                        else:
                            gc = c_g3.selectbox("牌种", ["杂牌", "幺鸡", "八筒"], key=K(f"gc{i}"),
                                                label_visibility="collapsed")
                        gv = None
                        if gt == "普通明杠":
                            gv = c_g4.selectbox("被杠者", [p for p in players if p != gw], key=K(f"gv{i}"),
                                                label_visibility="collapsed", placeholder="被杠者")
                        gang_data.append({'doer': gw, 'type': gt, 'card': gc, 'victim': gv})

                if fyw != "无/未现" and fyr == "被碰" and fyt:
                    yj_bu = st.checkbox(f"幺鸡被碰后补杠（补杠者：{fyt}）", value=False, key=K("yj_bu_gang"))
                    if yj_bu:
                        exists = False
                        for g in gang_data:
                            if g.get('type') == '补杠' and g.get('card') == '幺鸡' and g.get('doer') == fyt:
                                exists = True
                                break
                        if not exists:
                            gang_data.append({'doer': fyt, 'type': '补杠', 'card': '幺鸡', 'victim': None})
                            st.caption(f"ℹ️ 自动添加: {fyt} 补杠 (幺鸡)")

                if fbw != "无/未现" and fbr == "被碰" and fbt:
                    b8_bu = st.checkbox(f"八筒被碰后补杠（补杠者：{fbt}）", value=False, key=K("b8_bu_gang"))
                    if b8_bu:
                        exists = False
                        for g in gang_data:
                            if g.get('type') == '补杠' and g.get('card') == '八筒' and g.get('doer') == fbt:
                                exists = True
                                break
                        if not exists:
                            gang_data.append({'doer': fbt, 'type': '补杠', 'card': '八筒', 'victim': None})
                            st.caption(f"ℹ️ 自动添加: {fbt} 补杠 (八筒)")

                if st.button("➕ 添加", key=K("add_gang")):
                    st.session_state.gang_rows += 1
                    st.rerun()

    # --- Right column: sticky action bar + summary + results ---
    with right:
        st.markdown('<div class="sticky-panel">', unsafe_allow_html=True)

        st.markdown('<div class="action-bar">', unsafe_allow_html=True)
        st.markdown('<div class="glass-header" style="margin-bottom:10px;">⚡️ 快捷操作</div>', unsafe_allow_html=True)
        c_a1, c_a2 = st.columns([1.2, 1])
        with c_a1:
            settle_btn = st.button("💰 结算", type="primary", use_container_width=True, key=K("settle_btn"))
        with c_a2:
            reset_btn = st.button("🔄 重置", use_container_width=True, key=K("reset_btn"))
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="glass-header" style="margin-top:6px;">📌 本局概览</div>', unsafe_allow_html=True)

        chips = []
        w_cls = "ok" if winners else "warn"
        chips.append(f'<span class="chip {w_cls}">🎉 胡牌 {len(winners) if winners else 0}</span>')

        need_loser = (method == "点炮" and winners)
        l_ok = (not need_loser) or (loser is not None)
        l_cls = "ok" if l_ok else "warn"
        chips.append(
            f'<span class="chip {l_cls}">💥 点炮者 {"已选" if (loser is not None and method == "点炮") else ("不需要" if method == "自摸" else "未选")}</span>')

        r_cls = "ok" if (len(ready_list) > 0) else "warn"
        chips.append(f'<span class="chip {r_cls}">👂 听牌 {len(ready_list)}/{len(players)}</span>')

        f_cls = "ok" if (fan_card) else "warn"
        chips.append(f'<span class="chip {f_cls}">🎲 翻牌 {fan_card if fan_card else "无"}</span>')
        chips.append(f'<span class="chip">🐔 1条 {common_v["幺鸡"]} / 8筒 {common_v["八筒"]}</span>')

        st.markdown(' '.join(chips), unsafe_allow_html=True)
        st.write("")
        st.markdown('<div class="chip">🎉 胡牌者：' + ("、".join(winners) if winners else "未选") + '</div>',
                    unsafe_allow_html=True)
        st.markdown('<div class="chip">🧾 方式：' + method + (
            f'｜点炮：{loser}' if (method == "点炮" and loser) else "") + '</div>', unsafe_allow_html=True)

        st.write("")
        ui_divider("录入完成度")
        st.caption("提示：右侧固定栏用于随时结算/重置；左侧专注录入。")

        st.markdown('</div>', unsafe_allow_html=True)

        if reset_btn:
            reset_main_ui_state()
            st.rerun()

        if settle_btn:
            if not winners:
                st.error("必须选择至少1位胡牌者。")
                st.stop()
            if method == "点炮" and not loser:
                st.error("点炮必须选择点炮者。")
                st.stop()
            if (method == "点炮") and (("热炮" in special_events) or ("抢杠胡" in special_events)) and not loser:
                st.error("热炮/抢杠胡必须明确点炮者。")
                st.stop()

            try:
                scores, details = calculate_all(
                    players=players,
                    winners=winners,
                    method=method,
                    loser=loser,
                    hu_shape=hu_shape,
                    is_qing=is_qing,
                    special_events=special_events,
                    rules_config=rules_config,
                    fan_card=fan_card,
                    ready_list=ready_list,
                    first_yj_who=fyw, first_yj_res=fyr, first_yj_tar=fyt,
                    first_b8_who=fbw, first_b8_res=fbr, first_b8_tar=fbt,
                    extra_yj=extra_yj,
                    extra_b8=extra_b8,
                    hand_total_counts=hand_total_counts,
                    gang_data=gang_data,
                    common_v=common_v,
                    fan_unit=int(fan_unit)
                )
            except ValueError as e:
                st.error(str(e))
                st.stop()

            st.balloons()
            with st.container(border=True):
                ui_section("结算清单", icon="🧾")

                cred = sorted([[k, v] for k, v in scores.items() if v > 0], key=lambda x: x[1], reverse=True)
                debt = sorted([[k, -v] for k, v in scores.items() if v < 0], key=lambda x: x[1], reverse=True)

                i, j = 0, 0
                tx_html = ""
                while i < len(debt) and j < len(cred):
                    dn, da = debt[i];
                    cn, ca = cred[j]
                    amt = min(da, ca)
                    if amt > 0:
                        tx_html += f"""<div class="holo-ticket">
                            <div style="display:flex; align-items:center;">
                                <span class="tx-pay">{dn}</span><span class="tx-arrow">>>></span><span class="tx-get">{cn}</span>
                            </div>
                            <div class="tx-amt-box">¥ {int(amt)}</div>
                        </div>"""
                    debt[i][1] -= amt;
                    cred[j][1] -= amt
                    if debt[i][1] < 0.1: i += 1
                    if cred[j][1] < 0.1: j += 1

                if tx_html:
                    st.markdown(tx_html, unsafe_allow_html=True)
                elif all(s == 0 for s in scores.values()):
                    st.info("本局无分值变动。")
                else:
                    cols_res = st.columns(len(players))
                    for idx, p in enumerate(players):
                        cols_res[idx].metric(p, int(scores[p]))

                with st.expander("📄 查看详细账单"):
                    for p in players:
                        st.markdown(f"**{p}** ({int(scores[p])})")
                        for line in details[p]:
                            color = "green"
                            if ": -" in line:
                                color = "red"
                            elif ": +" in line:
                                color = "green"
                            st.markdown(f"- :{color}[{line}]")


if __name__ == "__main__":
    main()
