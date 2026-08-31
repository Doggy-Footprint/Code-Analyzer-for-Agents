"""
Unit tests for FastAPI Visualizer static analysis, graph builder, and renderer.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi_visualizer.analyzer import FastAPIAnalyzer
from fastapi_visualizer.graph import ArchitectureGraphBuilder
from fastapi_visualizer.renderer import HTMLRenderer


class TestFastAPIVisualizer(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.project_path = Path(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_sample_fastapi_app(self):
        """Creates a mini modular FastAPI project for testing."""
        # 1. Models
        models_dir = self.project_path / "app" / "models"
        models_dir.mkdir(parents=True, exist_ok=True)
        (models_dir / "__init__.py").write_text("")
        (models_dir / "user.py").write_text("""
from pydantic import BaseModel, EmailStr
from typing import Optional

class UserBase(BaseModel):
    email: EmailStr
    is_active: bool = True

class UserCreate(UserBase):
    password: str

class UserResponse(UserBase):
    id: int
""")

        # 2. Dependencies
        core_dir = self.project_path / "app" / "core"
        core_dir.mkdir(parents=True, exist_ok=True)
        (core_dir / "__init__.py").write_text("")
        (core_dir / "deps.py").write_text("""
from typing import Annotated, Generator
from fastapi import Depends, HTTPException
from app.models.user import UserResponse

def get_db() -> Generator:
    db = {"session": True}
    try:
        yield db
    finally:
        pass

SessionDep = Annotated[dict, Depends(get_db)]

def get_current_user(session: SessionDep) -> UserResponse:
    return UserResponse(id=1, email="test@example.com")

CurrentUser = Annotated[UserResponse, Depends(get_current_user)]
""")

        # 3. Routes / Endpoints
        routes_dir = self.project_path / "app" / "api" / "routes"
        routes_dir.mkdir(parents=True, exist_ok=True)
        (routes_dir / "__init__.py").write_text("")
        (routes_dir / "users.py").write_text("""
from fastapi import APIRouter, Depends, status
from app.models.user import UserCreate, UserResponse
from app.core.deps import CurrentUser, get_db

router = APIRouter(prefix="/users", tags=["users"])

@router.get("/me", response_model=UserResponse, summary="Get current user")
def read_user_me(current_user: CurrentUser):
    \"\"\"Return current authenticated user profile.\"\"\"
    return current_user

@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(user_in: UserCreate, db=Depends(get_db)):
    \"\"\"Register a new user.\"\"\"
    return UserResponse(id=2, email=user_in.email)
""")

        # 4. Main App
        app_dir = self.project_path / "app"
        (app_dir / "main.py").write_text("""
from fastapi import FastAPI
from app.api.routes.users import router as users_router

app = FastAPI(title="Sample API", version="2.0.0")
app.include_router(users_router, prefix="/api/v1")
""")

    def test_analyzer_extraction(self):
        self._create_sample_fastapi_app()
        analyzer = FastAPIAnalyzer(str(self.project_path))
        arch = analyzer.analyze()

        # Verify Apps
        self.assertEqual(len(arch.apps), 1)
        self.assertEqual(arch.apps[0].title, "Sample API")
        self.assertEqual(arch.apps[0].version, "2.0.0")

        # Verify Routers
        self.assertGreaterEqual(len(arch.routers), 1)
        users_router = next((r for r in arch.routers if "users" in r.var_name or "router" in r.var_name), None)
        self.assertIsNotNone(users_router)

        # Verify Endpoints
        self.assertEqual(len(arch.endpoints), 2)
        me_ep = next((ep for ep in arch.endpoints if "read_user_me" in ep.function_name), None)
        self.assertIsNotNone(me_ep)
        self.assertEqual(me_ep.http_method, "GET")
        self.assertEqual(me_ep.response_model, "UserResponse")
        self.assertEqual(me_ep.summary, "Get current user")
        self.assertIn("Return current authenticated user profile.", me_ep.docstring)

        # Verify Full Path Resolution (/api/v1 + /users + /me)
        self.assertEqual(me_ep.full_path, "/api/v1/users/me")

        # Verify Schemas
        schema_names = [s.name for s in arch.schemas]
        self.assertIn("UserCreate", schema_names)
        self.assertIn("UserResponse", schema_names)

        # Verify Dependencies and Annotated alias resolution
        dep_names = [d.name for d in arch.dependencies]
        self.assertIn("get_db", dep_names)
        self.assertIn("get_current_user", dep_names)

    def test_graph_building_and_rendering(self):
        self._create_sample_fastapi_app()
        analyzer = FastAPIAnalyzer(str(self.project_path))
        arch = analyzer.analyze()

        builder = ArchitectureGraphBuilder(include_models=True, include_dependencies=True)
        arch = builder.build_graph(arch)

        # Check nodes and edges created
        self.assertGreater(len(arch.nodes), 0)
        self.assertGreater(len(arch.edges), 0)

        # Check stats
        self.assertEqual(arch.stats["total_endpoints"], 2)
        self.assertEqual(arch.stats["methods_breakdown"]["GET"], 1)
        self.assertEqual(arch.stats["methods_breakdown"]["POST"], 1)

        # Check HTML rendering
        out_html = self.project_path / "output.html"
        renderer = HTMLRenderer(title="Test Visualizer")
        rendered_file = renderer.render(arch, str(out_html))

        self.assertTrue(rendered_file.exists())
        content = rendered_file.read_text(encoding="utf-8")
        self.assertIn("Sample API", content)
        self.assertIn("/api/v1/users/me", content)
        self.assertIn("UserResponse", content)
        self.assertIn("vis-network", content)

    def test_mermaid_generation(self):
        self._create_sample_fastapi_app()
        analyzer = FastAPIAnalyzer(str(self.project_path))
        arch = analyzer.analyze()
        builder = ArchitectureGraphBuilder()
        arch = builder.build_graph(arch)

        mermaid = builder.generate_mermaid(arch)
        self.assertTrue(mermaid.startswith("graph TD"))
        self.assertIn("Sample API", mermaid)

    def _init_git_repo(self):
        """Initializes a git repository in test_dir."""
        import subprocess
        subprocess.run(["git", "init"], cwd=self.project_path, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.project_path, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=self.project_path, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def _git_commit(self, msg: str):
        """Stages all changes and commits in test_dir."""
        import subprocess
        subprocess.run(["git", "add", "."], cwd=self.project_path, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "commit", "-m", msg], cwd=self.project_path, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_git_diff_non_git_repo(self):
        self._create_sample_fastapi_app()
        analyzer = FastAPIAnalyzer(str(self.project_path))
        arch = analyzer.analyze()

        self.assertIsNotNone(arch.git_diff)
        self.assertFalse(arch.git_diff.is_git_repo)
        self.assertEqual(arch.git_diff.comparison_mode, "none")

    def test_git_diff_working_tree_changes_and_untracked(self):
        self._create_sample_fastapi_app()
        self._init_git_repo()
        self._git_commit("initial commit")

        # 1. Modify an existing file
        main_file = self.project_path / "app" / "main.py"
        main_file.write_text(main_file.read_text() + "\n# new comment\n")

        # 2. Add an untracked file
        untracked_file = self.project_path / "app" / "untracked.py"
        untracked_file.write_text("x = 10\ny = 20\n")

        analyzer = FastAPIAnalyzer(str(self.project_path))
        arch = analyzer.analyze()

        self.assertIsNotNone(arch.git_diff)
        self.assertTrue(arch.git_diff.is_git_repo)
        self.assertTrue(arch.git_diff.has_uncommitted_changes)
        self.assertEqual(arch.git_diff.comparison_mode, "working_tree_vs_head")
        self.assertIsNotNone(arch.git_diff.base_commit)
        self.assertIsNone(arch.git_diff.target_commit)
        self.assertEqual(arch.git_diff.target_name, "Working Tree (Uncommitted Changes)")

        file_paths = [f.file_path for f in arch.git_diff.files]
        self.assertIn("app/main.py", file_paths)
        self.assertIn("app/untracked.py", file_paths)

        # Check untracked file diff
        untracked_diff = next(f for f in arch.git_diff.files if f.file_path == "app/untracked.py")
        self.assertEqual(untracked_diff.status, "untracked")
        self.assertEqual(untracked_diff.additions, 2)
        self.assertEqual(untracked_diff.deletions, 0)
        self.assertGreaterEqual(len(untracked_diff.hunks), 1)

    def test_git_diff_clean_working_tree_last_two_commits(self):
        self._create_sample_fastapi_app()
        self._init_git_repo()
        self._git_commit("commit 1 - base architecture")

        # Create a second commit
        new_route_file = self.project_path / "app" / "api" / "routes" / "items.py"
        new_route_file.write_text("""
from fastapi import APIRouter
router = APIRouter(prefix="/items")
@router.get("/")
def get_items():
    return [{"id": 1}]
""")
        self._git_commit("commit 2 - add items endpoint")

        # Working tree is clean now (no uncommitted changes, no untracked files)
        analyzer = FastAPIAnalyzer(str(self.project_path))
        arch = analyzer.analyze()

        self.assertIsNotNone(arch.git_diff)
        self.assertTrue(arch.git_diff.is_git_repo)
        self.assertFalse(arch.git_diff.has_uncommitted_changes)
        self.assertEqual(arch.git_diff.comparison_mode, "last_two_commits")
        self.assertIsNotNone(arch.git_diff.base_commit)
        self.assertIsNotNone(arch.git_diff.target_commit)
        self.assertIn("commit 1", arch.git_diff.base_commit.message)
        self.assertIn("commit 2", arch.git_diff.target_commit.message)

        file_paths = [f.file_path for f in arch.git_diff.files]
        self.assertIn("app/api/routes/items.py", file_paths)

    def test_git_diff_impacted_endpoints(self):
        self._create_sample_fastapi_app()
        self._init_git_repo()
        self._git_commit("initial commit")

        # Modify users.py which contains endpoints
        users_file = self.project_path / "app" / "api" / "routes" / "users.py"
        content = users_file.read_text()
        users_file.write_text(content + "\n# added note\n")

        analyzer = FastAPIAnalyzer(str(self.project_path))
        arch = analyzer.analyze()

        self.assertIsNotNone(arch.git_diff)
        impacted_paths = [ep["path"] for ep in arch.git_diff.impacted_endpoints]
        self.assertIn("/api/v1/users/me", impacted_paths)

    def test_html_rendering_with_git_diff(self):
        self._create_sample_fastapi_app()
        self._init_git_repo()
        self._git_commit("initial commit")

        # Add changes
        (self.project_path / "app" / "main.py").write_text("# modified\n")

        analyzer = FastAPIAnalyzer(str(self.project_path))
        arch = analyzer.analyze()
        builder = ArchitectureGraphBuilder()
        arch = builder.build_graph(arch)

        renderer = HTMLRenderer(title="Git Diff Test")
        out_html = self.project_path / "report.html"
        rendered = renderer.render(arch, str(out_html))

        html_text = rendered.read_text(encoding="utf-8")
        self.assertIn("tab-btn-gitdiff", html_text)
        self.assertIn("view-gitdiff", html_text)
        self.assertIn("populateGitDiff", html_text)
        self.assertIn("git-diff-hero", html_text)
        self.assertIn("working_tree_vs_head", html_text)


if __name__ == "__main__":
    unittest.main()

