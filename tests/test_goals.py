import unittest
from datetime import date
from app.goals import calculate_goal

class GoalTests(unittest.TestCase):
    def test_modes(self):
        p = {'birth_date':date(1988,10,11),'sex_for_bmr':'male','height_cm':170,'current_weight_kg':78,'activity_level':'moderate'}
        cut = calculate_goal(p,'cutting',date(2026,10,13))
        keep = calculate_goal(p,'maintenance',date(2026,10,13))
        bulk = calculate_goal(p,'bulking',date(2026,10,13))
        self.assertLess(cut['calories'],keep['calories'])
        self.assertLess(keep['calories'],bulk['calories'])
        self.assertEqual(cut['protein'],156)

if __name__ == '__main__': unittest.main()
