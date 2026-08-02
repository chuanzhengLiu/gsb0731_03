from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from itertools import permutations
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)


TAG_VOCABULARY = [
    '冷静理智', '情感丰富', '搞笑担当', '领导力强', '逻辑推理',
    '社交活跃', '细腻敏感', '沉默寡言', '冒险精神', '团队协作',
]

PREFERENCE_TO_PERSONALITY_MAP = {
    '推理型': ['冷静理智', '逻辑推理', '沉默寡言'],
    '情感型': ['情感丰富', '细腻敏感'],
    '活跃型': ['社交活跃', '冒险精神', '搞笑担当'],
    '沉浸型': ['情感丰富', '细腻敏感', '团队协作'],
    '搞笑型': ['搞笑担当', '社交活跃', '领导力强'],
    '领导型': ['领导力强', '逻辑推理', '冷静理智'],
    '辅助型': ['团队协作', '细腻敏感', '情感丰富'],
    '新手型': ['团队协作', '情感丰富'],
    '老玩家型': ['逻辑推理', '领导力强', '冒险精神'],
}


@dataclass
class MatchPlayer:
    name: str
    phone: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    horror_tolerance: int = 0
    accept_reverse: bool = False
    player_profile_id: Optional[int] = None
    gender: Optional[str] = None
    history_roles: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class MatchRole:
    role_id: int
    role_name: str
    personality_tags: List[str] = field(default_factory=list)
    suggested_gender: str = 'any'


@dataclass
class MatchBreakdown:
    personality_score: float = 0.0
    gender_score: float = 0.0
    horror_score: float = 0.0
    history_score: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        return {
            'a_score': round(self.personality_score, 2),
            'b_score': round(self.gender_score, 2),
            'c_score': round(self.horror_score, 2),
            'd_score': round(self.history_score, 2),
        }

    @property
    def total(self) -> float:
        return self.personality_score + self.gender_score + self.horror_score + self.history_score


@dataclass
class MatchAssignment:
    player_name: str
    player_phone: Optional[str]
    player_index: int
    role_id: int
    role_name: str
    match_score: float
    breakdown: MatchBreakdown

    def to_dict(self) -> Dict[str, Any]:
        return {
            'player_name': self.player_name,
            'player_phone': self.player_phone,
            'role_id': self.role_id,
            'role_name': self.role_name,
            'match_score': round(self.match_score, 2),
            'breakdown': self.breakdown.to_dict(),
        }


@dataclass
class MatchResult:
    assignments: List[MatchAssignment]
    alternative_suggestions: List[List[MatchAssignment]]
    total_score: float
    avg_score: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            'assignments': [a.to_dict() for a in self.assignments],
            'alternative_suggestions': [
                [a.to_dict() for a in alt]
                for alt in self.alternative_suggestions
            ],
            'total_score': round(self.total_score, 2),
            'avg_score': round(self.avg_score, 2),
        }


def _expand_player_tags(player_tags: List[str]) -> List[str]:
    expanded = set()
    for tag in player_tags:
        if tag in TAG_VOCABULARY:
            expanded.add(tag)
        if tag in PREFERENCE_TO_PERSONALITY_MAP:
            for pt in PREFERENCE_TO_PERSONALITY_MAP[tag]:
                expanded.add(pt)
    return list(expanded)


def _cosine_similarity(tags_a: List[str], tags_b: List[str]) -> float:
    if not tags_a or not tags_b:
        return 0.0

    vocab = TAG_VOCABULARY
    vec_a = [1.0 if t in tags_a else 0.0 for t in vocab]
    vec_b = [1.0 if t in tags_b else 0.0 for t in vocab]

    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)


def _calc_personality_score(player: MatchPlayer, role: MatchRole) -> float:
    expanded_tags = _expand_player_tags(player.tags)
    similarity = _cosine_similarity(expanded_tags, role.personality_tags)
    return round(similarity * 40, 2)


def _calc_gender_score(player: MatchPlayer, role: MatchRole) -> float:
    suggested = role.suggested_gender.lower()

    if suggested == 'any':
        return 30.0

    if player.accept_reverse:
        return 25.0

    player_gender = (player.gender or '').lower()
    if not player_gender or player_gender == 'other':
        return 15.0

    if player_gender == suggested:
        return 30.0

    return 0.0


def _calc_horror_score(player: MatchPlayer, is_horror_script: bool) -> float:
    if not is_horror_script:
        return 15.0

    tolerance = player.horror_tolerance
    if tolerance >= 2:
        return 15.0
    elif tolerance == 1:
        return 8.0
    else:
        return 0.0


def _calc_history_score(
    player: MatchPlayer,
    role: MatchRole,
    script_type: str,
    all_roles: List[MatchRole],
) -> float:
    history = player.history_roles
    if not history:
        return 15.0

    same_type_roles = []
    for hist in history:
        hist_script_type = hist.get('script_type', '')
        if hist_script_type and hist_script_type == script_type:
            same_type_roles.append(hist)
        elif not hist_script_type:
            same_type_roles.append(hist)

    if not same_type_roles:
        return 15.0

    role_personality_set = set(role.personality_tags)
    worst_score = 15.0

    for hist in same_type_roles:
        hist_role_name = hist.get('role_name', '')
        if hist_role_name and hist_role_name == role.role_name:
            return 0.0

        hist_tags = hist.get('personality_tags', [])
        if not hist_tags:
            hist_role_id = hist.get('role_id')
            if hist_role_id:
                for ar in all_roles:
                    if ar.role_id == hist_role_id:
                        hist_tags = ar.personality_tags
                        break

        hist_tag_set = set(hist_tags)
        common_count = len(role_personality_set & hist_tag_set)

        if common_count >= 3:
            score = 5.0
        else:
            score = 15.0

        if score < worst_score:
            worst_score = score

    return worst_score


def calculate_match_score(
    player: MatchPlayer,
    role: MatchRole,
    is_horror_script: bool,
    script_type: str,
    all_roles: List[MatchRole],
) -> Tuple[float, MatchBreakdown]:
    breakdown = MatchBreakdown()
    breakdown.personality_score = _calc_personality_score(player, role)
    breakdown.gender_score = _calc_gender_score(player, role)
    breakdown.horror_score = _calc_horror_score(player, is_horror_script)
    breakdown.history_score = _calc_history_score(player, role, script_type, all_roles)

    total = breakdown.total
    total = max(0.0, min(100.0, total))

    return round(total, 2), breakdown


def _hungarian_algorithm(cost_matrix: List[List[float]]) -> List[int]:
    n = len(cost_matrix)
    if n == 0:
        return []

    INF = float('inf')

    u = [0] * (n + 1)
    v = [0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)

    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (n + 1)
        used = [False] * (n + 1)

        while True:
            used[j0] = True
            i0 = p[j0]
            delta = INF
            j1 = -1

            for j in range(1, n + 1):
                if not used[j]:
                    if i0 - 1 < len(cost_matrix) and j - 1 < len(cost_matrix[i0 - 1]):
                        cur = cost_matrix[i0 - 1][j - 1] - u[i0] - v[j]
                    else:
                        cur = INF

                    if cur < minv[j]:
                        minv[j] = cur
                        way[j] = j0

                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j

            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta

            j0 = j1
            if p[j0] == 0:
                break

        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break

    assignment = [-1] * n
    for j in range(1, n + 1):
        if p[j] >= 1 and p[j] <= n:
            assignment[p[j] - 1] = j - 1

    return assignment


def _build_score_matrix(
    players: List[MatchPlayer],
    roles: List[MatchRole],
    is_horror_script: bool,
    script_type: str,
) -> Tuple[List[List[float]], List[List[MatchBreakdown]]]:
    n = max(len(players), len(roles))
    score_matrix = [[0.0] * n for _ in range(n)]
    breakdown_matrix = [[MatchBreakdown() for _ in range(n)] for _ in range(n)]

    for i, player in enumerate(players):
        for j, role in enumerate(roles):
            score, breakdown = calculate_match_score(
                player, role, is_horror_script, script_type, roles
            )
            score_matrix[i][j] = score
            breakdown_matrix[i][j] = breakdown

    return score_matrix, breakdown_matrix


def _assignments_from_permutation(
    permutation: List[int],
    players: List[MatchPlayer],
    roles: List[MatchRole],
    score_matrix: List[List[float]],
    breakdown_matrix: List[List[MatchBreakdown]],
) -> List[MatchAssignment]:
    assignments = []
    for player_idx, role_idx in enumerate(permutation):
        if player_idx >= len(players) or role_idx >= len(roles):
            continue
        player = players[player_idx]
        role = roles[role_idx]
        assignments.append(MatchAssignment(
            player_name=player.name,
            player_phone=player.phone,
            player_index=player_idx,
            role_id=role.role_id,
            role_name=role.role_name,
            match_score=score_matrix[player_idx][role_idx],
            breakdown=breakdown_matrix[player_idx][role_idx],
        ))
    return assignments


def _generate_alternatives(
    score_matrix: List[List[float]],
    breakdown_matrix: List[List[MatchBreakdown]],
    players: List[MatchPlayer],
    roles: List[MatchRole],
    best_permutation: List[int],
    top_k: int = 3,
) -> List[List[MatchAssignment]]:
    n = min(len(players), len(roles))
    if n <= 1 or n > 8:
        return []

    all_indices = list(range(n))
    perm_list = list(permutations(all_indices))

    scored_perms = []
    best_total = sum(
        score_matrix[i][best_permutation[i]] for i in range(n)
    ) if len(best_permutation) >= n else 0

    for perm in perm_list:
        perm_list_int = list(perm)
        if perm_list_int == best_permutation[:n]:
            continue
        total = sum(score_matrix[i][perm_list_int[i]] for i in range(n))
        if total < best_total * 0.7:
            continue
        scored_perms.append((total, perm_list_int))

    scored_perms.sort(key=lambda x: x[0], reverse=True)

    alternatives = []
    seen = set()
    for total, perm in scored_perms[:top_k + 5]:
        perm_tuple = tuple(perm)
        if perm_tuple in seen:
            continue
        seen.add(perm_tuple)

        full_perm = perm + list(range(n, len(roles)))
        assignments = _assignments_from_permutation(
            full_perm, players, roles, score_matrix, breakdown_matrix
        )
        alternatives.append(assignments)

        if len(alternatives) >= top_k:
            break

    return alternatives


def run_role_matching(
    players: List[MatchPlayer],
    roles: List[MatchRole],
    is_horror_script: bool = False,
    script_type: str = '',
) -> MatchResult:
    if not players or not roles:
        return MatchResult(
            assignments=[],
            alternative_suggestions=[],
            total_score=0.0,
            avg_score=0.0,
        )

    n_players = len(players)
    n_roles = len(roles)

    if n_players != n_roles:
        logger.warning(
            f'玩家数量({n_players})与角色数量({n_roles})不匹配，'
            f'可能无法完全分配'
        )

    score_matrix, breakdown_matrix = _build_score_matrix(
        players, roles, is_horror_script, script_type
    )

    n = max(n_players, n_roles)
    cost_matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i < n_players and j < n_roles:
                cost_matrix[i][j] = 100.0 - score_matrix[i][j]
            else:
                cost_matrix[i][j] = 1000.0

    assignment = _hungarian_algorithm(cost_matrix)

    best_permutation = [-1] * n_players
    for player_idx in range(n_players):
        if player_idx < len(assignment):
            role_idx = assignment[player_idx]
            if 0 <= role_idx < n_roles:
                best_permutation[player_idx] = role_idx

    for i in range(n_players):
        if best_permutation[i] == -1:
            used_roles = set(best_permutation)
            for j in range(n_roles):
                if j not in used_roles:
                    best_permutation[i] = j
                    break

    assignments = []
    total_score = 0.0
    valid_count = 0
    for player_idx in range(n_players):
        role_idx = best_permutation[player_idx]
        if role_idx < 0 or role_idx >= n_roles:
            continue
        player = players[player_idx]
        role = roles[role_idx]
        score = score_matrix[player_idx][role_idx]
        breakdown = breakdown_matrix[player_idx][role_idx]
        assignments.append(MatchAssignment(
            player_name=player.name,
            player_phone=player.phone,
            player_index=player_idx,
            role_id=role.role_id,
            role_name=role.role_name,
            match_score=score,
            breakdown=breakdown,
        ))
        total_score += score
        valid_count += 1

    avg_score = total_score / valid_count if valid_count > 0 else 0.0

    alternative_suggestions = _generate_alternatives(
        score_matrix,
        breakdown_matrix,
        players,
        roles,
        best_permutation,
        top_k=3,
    )

    return MatchResult(
        assignments=assignments,
        alternative_suggestions=alternative_suggestions,
        total_score=total_score,
        avg_score=avg_score,
    )
