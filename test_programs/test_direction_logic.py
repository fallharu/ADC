import unittest
import math
from Source_code.modules.manual_metrics import select_measure_point_from_candidates, select_bicycle_tire_measure_point

# Mock helpers
def create_det(x1, y1, x2, y2, measure_x=None, measure_y=None):
    d = {"x1": x1, "y1": y1, "x2": x2, "y2": y2}
    if measure_x: d["measure_x"] = measure_x
    if measure_y: d["measure_y"] = measure_y
    return d

# Mock white lines (simple vertical lines for testing)
# Left at x=100, Right at x=900
LEFT_LINE = [[100, 0], [100, 1000]]
RIGHT_LINE = [[900, 0], [900, 1000]]

class TestDirectionLogic(unittest.TestCase):
    
    def test_up_to_down_car(self):
        # Case: Car moving up-to-down (towards camera) -> Should prefer Right (x2)
        # Setup: Candidate with x1=400, x2=600. x1 is closer to left line (300px), x2 is closer to right line (300px)
        # Let's make x1 closer to a line to see if direction overrides distance logic
        
        # x1=200 (dist 100 to left), x2=400 (dist 500 to right)
        # Normal logic: x1 is closer, so select x1.
        # Up-To-Down logic: Should Select x2 (Right) even if x1 is closer?
        # User requirement: "上から下の場合は 右寄り" -> implied forcing right side.
        
        det = create_det(200, 500, 400, 700)
        candidates = [det]
        
        # 1. Unknown direction (fallback to white line distance)
        # x1(200) dist=100, x2(400) dist=500 -> Expect x1
        mx, my = select_measure_point_from_candidates(candidates, LEFT_LINE, RIGHT_LINE, direction='unknown')
        self.assertEqual(mx, 200, "Unknown direction should pick closer point (x1)")
        
        # 2. Up-To-Down direction
        # Expect x2 (Right side)
        mx, my = select_measure_point_from_candidates(candidates, LEFT_LINE, RIGHT_LINE, direction='up_to_down')
        self.assertEqual(mx, 400, "Up-To-Down should force pick right point (x2)")

    def test_down_to_up_car(self):
        # Case: Car moving down-to-up (away) -> Should prefer Left (x1)
        
        # x1=600 (dist 300 to right, 500 to left), x2=800 (dist 100 to right)
        # Normal logic: x2 is closer (100 vs 300), so select x2.
        # Down-To-Up logic: Should Select x1 (Left side) logic.
        
        det = create_det(600, 500, 800, 700)
        candidates = [det]
        
        # 1. Unknown (expect x2)
        mx, my = select_measure_point_from_candidates(candidates, LEFT_LINE, RIGHT_LINE, direction='unknown')
        self.assertEqual(mx, 800, "Unknown direction should pick closer point (x2)")
        
        # 2. Down-To-Up (expect x1)
        mx, my = select_measure_point_from_candidates(candidates, LEFT_LINE, RIGHT_LINE, direction='down_to_up')
        self.assertEqual(mx, 600, "Down-To-Up should force pick left point (x1)")

    def test_bicycle_logic(self):
        # Bicycle Logic: 
        # Up-To-Down: "Closest to white line" (Same as unknown)
        # Down-To-Up: Left side (x1)
        
        # Case A: x2 is closer to white line
        det = create_det(600, 500, 800, 700) # x2(800) is dist 100, x1(600) is dist 300
        candidates = [det]
        bbox_source = det
        
        # 1. Up-To-Down -> Expect x2 (Closer one)
        mx, my = select_bicycle_tire_measure_point(bbox_source, candidates, LEFT_LINE, RIGHT_LINE, direction='up_to_down')
        self.assertEqual(mx, 800, "Bicycle Up-To-Down should keep picking closer point (x2)")
        
        # 2. Down-To-Up -> Expect x1 (Left side, forced)
        mx, my = select_bicycle_tire_measure_point(bbox_source, candidates, LEFT_LINE, RIGHT_LINE, direction='down_to_up')
        self.assertEqual(mx, 600, "Bicycle Down-To-Up should force pick left point (x1)")


if __name__ == '__main__':
    unittest.main()
