"""Deterministic starting calorie recommendations, subject to user confirmation."""
from datetime import date

ACTIVITY = {'sedentary':1.2,'light':1.375,'moderate':1.55,'active':1.725,'very_active':1.9}
ADJUST = {'cutting':-15,'maintenance':0,'bulking':10}

def calculate_goal(profile: dict, mode: str, today: date) -> dict:
    if mode not in ADJUST:
        raise ValueError('Unknown goal mode')
    birth = profile['birth_date']
    age = today.year - birth.year - ((today.month,today.day) < (birth.month,birth.day))
    if not 18 <= age <= 100:
        raise ValueError('Automatic calculation requires adult profile')
    weight = float(profile['current_weight_kg'])
    height = float(profile['height_cm'])
    sex = profile['sex_for_bmr']
    if sex not in ('male','female'):
        raise ValueError('BMR formula needs a selected reference; use manual target otherwise')
    bmr = 10*weight + 6.25*height - 5*age + (5 if sex=='male' else -161)
    maintenance = round(bmr * ACTIVITY[profile['activity_level']])
    calories = round(maintenance * (1 + ADJUST[mode]/100))
    calories = max(calories, 1500 if sex=='male' else 1200)
    protein = round(weight * (2.0 if mode=='cutting' else 1.8))
    return {'mode':mode,'adjustment':ADJUST[mode], 'maintenance':maintenance,'calories':calories,'protein':protein}
