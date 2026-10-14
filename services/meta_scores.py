"""Deterministic integer allocation of pedagogical weights; no text heuristics."""
import math
from fractions import Fraction

from services.lesson_validation import LessonValidationError

# Relative complexity of the explicit Bloom level, independent of wording/language.
LEVEL_WEIGHTS = (1, 2, 3, 4, 4, 5)


def weight(value, *, task_id=None):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and value > 0
    except (ValueError, OverflowError):
        valid = False
    if not valid:
        raise LessonValidationError('Вес оценивания должен быть конечным положительным числом.',
                                    code='invalid_score_weight', task_id=task_id)
    return Fraction(str(value))


def allocate_scores(weights, total=100, minimums=None, maximums=None):
    """Bounded proportional quotas, then largest remainders (ties: source order)."""
    weights = [weight(value) if not isinstance(value, Fraction) else value for value in weights]
    count = len(weights)
    minimums = [1] * count if minimums is None else minimums
    maximums = [total] * count if maximums is None else maximums
    if (type(total) is not int or total < 0 or not count or any(w <= 0 for w in weights) or
        len(minimums) != count or len(maximums) != count or
        any(type(lo) is not int or type(hi) is not int or lo < 0 or hi < lo for lo, hi in zip(minimums, maximums)) or
        sum(minimums) > total or sum(maximums) < total):
        raise LessonValidationError('Невозможно распределить баллы с указанными границами.', code='impossible_score_allocation')
    # Piecewise linear sum(clamp(scale * weight, min, max)); exact rational root.
    breaks = sorted({Fraction(0)} | {Fraction(bound) / w for w, lo, hi in zip(weights, minimums, maximums) for bound in (lo, hi)})
    def clipped(scale):
        return [min(Fraction(hi), max(Fraction(lo), scale * w)) for w, lo, hi in zip(weights, minimums, maximums)]
    quotas = None
    for left, right in zip(breaks, breaks[1:]):
        low_values, high_values = clipped(left), clipped(right)
        low_sum, high_sum = sum(low_values), sum(high_values)
        if low_sum <= total <= high_sum:
            scale = left if low_sum == high_sum else left + (right - left) * (total - low_sum) / (high_sum - low_sum)
            quotas = clipped(scale)
            break
    if quotas is None:
        quotas = clipped(breaks[-1])
    values = [int(q) for q in quotas]
    order = sorted(range(count), key=lambda i: (-(quotas[i] - values[i]), i))
    for i in [i for i in order if values[i] < maximums[i]][:total - sum(values)]:
        values[i] += 1
    if sum(values) != total or any(not lo <= v <= hi for v, lo, hi in zip(values, minimums, maximums)):
        raise LessonValidationError('Невозможно распределить баллы.', code='impossible_score_allocation')
    return values


def normalize_assessment_points(items, language):
    from services.lesson_validation import BLOOM_LEVELS
    levels = [level.casefold() for level in BLOOM_LEVELS[language]]
    configured = [Fraction(LEVEL_WEIGHTS[levels.index(item['bloom_level'].casefold())]) for item in items]
    proposed = [weight(item['points'], task_id=item['task_id']) if 'points' in item else None for item in items]
    supplied_indexes = [i for i, value in enumerate(proposed) if value is not None]
    # Missing weights use the same units as the supplied weights, not an arbitrary 1.
    scale = (sum(proposed[i] for i in supplied_indexes) / sum(configured[i] for i in supplied_indexes)
             if supplied_indexes else Fraction(1))
    weights = [value if value is not None else configured[i] * scale for i, value in enumerate(proposed)]
    scores = allocate_scores(weights, minimums=[item.get('points_min', 1) for item in items],
                             maximums=[item.get('points_max', 100) for item in items])
    for item, maximum in zip(items, scores):
        descriptor_weights = item.pop('_descriptor_weights')
        supplied = item.get('descriptor_points')
        if supplied is not None:
            if not isinstance(supplied, list) or len(supplied) != len(descriptor_weights):
                raise LessonValidationError('Баллы дескрипторов не соответствуют дескрипторам.', code='descriptor_points_mismatch', task_id=item['task_id'])
            supplied = [weight(value, task_id=item['task_id']) for value in supplied]
            if any(value is not None and value != other for value, other in zip(descriptor_weights, supplied)):
                raise LessonValidationError('Две структуры весов дескрипторов противоречат друг другу.', code='descriptor_points_mismatch', task_id=item['task_id'])
            descriptor_weights = supplied
        # No complexity metadata per descriptor: missing values use the mean supplied unit.
        provided = [value for value in descriptor_weights if value is not None]
        unit = sum(provided) / len(provided) if provided else Fraction(1)
        descriptor_weights = [unit if value is None else value for value in descriptor_weights]
        item['points'] = maximum
        item['descriptor_points'] = allocate_scores(descriptor_weights, maximum, minimums=[0] * len(descriptor_weights))

