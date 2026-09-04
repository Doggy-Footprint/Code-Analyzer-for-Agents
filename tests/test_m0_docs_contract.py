import unittest
from pathlib import Path


class M0DocumentationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.readme = (root / "README.md").read_text(encoding="utf-8")
        cls.roadmap = (root / "ROADMAP.md").read_text(encoding="utf-8")

    def test_roadmap_records_m0_as_complete_and_classifies_existing_features(self):
        self.assertIn("### M0. 문서와 계약 재정렬 — 완료", self.roadmap)
        self.assertIn(
            "| 유지 | 언어·프레임워크 analyzer, 정적 관계와 근거, effective·weighted 지표를 포함한 graph metric, renderer |",
            self.roadmap,
        )
        self.assertIn(
            "| 교체·확장 | 기존 symbol graph는 M1 readable·query node로, serialization과 CLI 출력은 각 milestone 계약으로 확장한다. 현재 graph metric은 M4 입력이며 M4 완료를 뜻하지 않는다. |",
            self.roadmap,
        )
        self.assertIn(
            "| 제거 | 이전 exploration cost, task difficulty, 저장소 cost diff, git diff 영향 분석, 구조적 마찰 진단, Android inject-field 임의 비용·경고 |",
            self.roadmap,
        )

    def test_roadmap_records_m1_as_complete(self):
        self.assertIn("### M1. Agent-view graph — 완료", self.roadmap)

    def test_readme_states_its_blankness_is_intentional_and_only_points_at_documents(self):
        self.assertIn("Left blank for intent.", self.readme)
        self.assertIn("[ROADMAP.md](ROADMAP.md)", self.readme)
        self.assertNotIn("## 그래프 모델", self.readme)
        self.assertNotIn("## 비용 계약", self.readme)
        self.assertLess(len(self.readme), len(self.roadmap))


if __name__ == "__main__":
    unittest.main()
