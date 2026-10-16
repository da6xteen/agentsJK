from typing import List, Dict, Any, Tuple

FACTOR_WEIGHTS: Dict[str, int] = {
    "R1": 35, # Установлено отсутствие применимого правового основания
    "R2": 25, # Прямое предложение внести деньги
    "R3": 10, # Реклама строящегося жилья
    "R4": 15, # Отсутствие гарантии КЖК / разрешения МИО
    "R5": 10, # Иные выявленные несоответствия
    "R6": 5,  # Минорные риски
}

def calculate_risk_score(confirmed_factors: List[str]) -> Tuple[int, str, str]:
    """
    Calculates deterministic risk score and risk zone based strictly on confirmed factor IDs.
    Returns: (score, zone_code, zone_label)
    - zone_code: 'green' | 'yellow' | 'red'
    - score: min(100, sum of weights)
    """
    factors_set = set(confirmed_factors)
    raw_score = sum(FACTOR_WEIGHTS.get(factor, 0) for factor in factors_set)
    score = min(100, raw_score)

    has_r1 = "R1" in factors_set
    has_r2 = "R2" in factors_set

    # Risk zones:
    # Зелёная: 0–24
    # Жёлтая: 25–59; либо 60+ если нет пары R1+R2
    # Красная: 60+ И одновременно подтверждены R1 и R2
    if score >= 60 and has_r1 and has_r2:
        zone_code = "red"
        zone_label = "Высокий риск (обнаружены признаки риска)"
    elif score >= 25:
        zone_code = "yellow"
        zone_label = "Средний риск (требуется проверка аналитиком)"
    else:
        zone_code = "green"
        zone_label = "Низкий риск"

    return score, zone_code, zone_label
