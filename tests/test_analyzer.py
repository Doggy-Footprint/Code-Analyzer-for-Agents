"""
Unit tests for FastAPI Visualizer static analysis, graph builder, and renderer.
"""

import ast
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from framework_analyzers.fastapi.analyzer import FastAPIAnalyzer
import framework_analyzers.fastapi.graph as fastapi_graph
from framework_analyzers.fastapi.graph import ArchitectureGraphBuilder
from framework_analyzers.fastapi.models import EndpointInfo, ProjectArchitecture, SchemaInfo
from language_analyzers.core.graph_models import Resolution
from renderers.html import HTMLRenderer


class TestFastAPIVisualizer(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.project_path = Path(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_sample_fastapi_app(self):
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

        self.assertEqual(len(arch.apps), 1)
        self.assertEqual(arch.apps[0].title, "Sample API")
        self.assertEqual(arch.apps[0].version, "2.0.0")

        self.assertGreaterEqual(len(arch.routers), 1)
        users_router = next((r for r in arch.routers if "users" in r.var_name or "router" in r.var_name), None)
        self.assertIsNotNone(users_router)

        self.assertEqual(len(arch.endpoints), 2)
        me_ep = next((ep for ep in arch.endpoints if "read_user_me" in ep.function_name), None)
        self.assertIsNotNone(me_ep)
        self.assertEqual(me_ep.http_method, "GET")
        self.assertEqual(me_ep.response_model, "UserResponse")
        self.assertEqual(me_ep.summary, "Get current user")
        self.assertIn("Return current authenticated user profile.", me_ep.docstring)

        self.assertEqual(me_ep.full_path, "/api/v1/users/me")

        schema_names = [s.name for s in arch.schemas]
        self.assertIn("UserCreate", schema_names)
        self.assertIn("UserResponse", schema_names)

        dep_names = [d.name for d in arch.dependencies]
        self.assertIn("get_db", dep_names)
        self.assertIn("get_current_user", dep_names)

    def test_graph_building_and_rendering(self):
        self._create_sample_fastapi_app()
        analyzer = FastAPIAnalyzer(str(self.project_path))
        arch = analyzer.analyze()

        builder = ArchitectureGraphBuilder(include_models=True, include_dependencies=True)
        arch = builder.build_graph(arch)

        self.assertGreater(len(arch.nodes), 0)
        self.assertGreater(len(arch.edges), 0)

        self.assertEqual(arch.stats["total_endpoints"], 2)
        self.assertEqual(arch.stats["methods_breakdown"]["GET"], 1)
        self.assertEqual(arch.stats["methods_breakdown"]["POST"], 1)
        self.assertIn("analysis", arch.stats)
        self.assertEqual(len(arch.stats["analysis"]["node_metrics"]), len(arch.nodes))
        self.assertTrue(all("analysis" in node.metadata for node in arch.nodes))

        out_html = self.project_path / "output.html"
        renderer = HTMLRenderer(title="Test Visualizer")
        rendered_file = renderer.render(arch, str(out_html))

        self.assertTrue(rendered_file.exists())
        content = rendered_file.read_text(encoding="utf-8")
        self.assertIn("Sample API", content)
        self.assertIn("/api/v1/users/me", content)
        self.assertIn("UserResponse", content)
        self.assertIn("vis-network", content)
        asset_dir = self.project_path / "output_assets"
        self.assertTrue((asset_dir / "styles.css").exists())
        self.assertTrue((asset_dir / "tailwind-config.js").exists())
        self.assertTrue((asset_dir / "app.js").exists())
        self.assertNotIn("<style>", content)

    def test_built_framework_edges_carry_their_declared_rule(self):
        self._create_sample_fastapi_app()
        arch = ArchitectureGraphBuilder().build_graph(FastAPIAnalyzer(str(self.project_path)).analyze())

        framework_edges = [
            edge for edge in arch.edges
            if str(edge.confidence) == "framework_inferred"
        ]
        undeclared = [
            edge.relation for edge in framework_edges
            if "framework_rule" not in (edge.metadata or {})
        ]
        implemented_by = [edge for edge in framework_edges if edge.relation == "IMPLEMENTED_BY"]

        self.assertGreater(len(framework_edges), 0)
        self.assertEqual(undeclared, [])
        self.assertGreater(len(implemented_by), 0)
        self.assertEqual(
            implemented_by[0].metadata["framework_rule"],
            {"id": "fastapi.implemented_by", "specificity": "unique"},
        )
        routes = [edge for edge in framework_edges if edge.relation == "ROUTES"]
        self.assertGreater(len(routes), 0)
        self.assertEqual(
            routes[0].metadata["framework_rule"],
            {"id": "fastapi.routes", "specificity": "unique"},
        )

    def test_mermaid_generation(self):
        self._create_sample_fastapi_app()
        analyzer = FastAPIAnalyzer(str(self.project_path))
        arch = analyzer.analyze()
        builder = ArchitectureGraphBuilder()
        arch = builder.build_graph(arch)

        mermaid = builder.generate_mermaid(arch)
        self.assertTrue(mermaid.startswith("graph TD"))
        self.assertIn("Sample API", mermaid)


class FastAPIFrameworkRuleDeclarationTests(unittest.TestCase):
    def test_every_emitted_framework_relation_declares_a_rule(self):
        source = Path(fastapi_graph.__file__).read_text(encoding="utf-8")
        emitted = {
            keyword.value.value
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            for keyword in node.keywords
            if keyword.arg == "relation"
            and isinstance(keyword.value, ast.Constant)
            and isinstance(keyword.value.value, str)
        }

        undeclared = emitted - set(ArchitectureGraphBuilder.FRAMEWORK_RULE_SPECIFICITY)

        self.assertEqual(undeclared, set())

    def test_declared_specificities_are_within_the_contract(self):
        self.assertEqual(
            set(ArchitectureGraphBuilder.FRAMEWORK_RULE_SPECIFICITY.values()) - {"unique", "narrowing"},
            set(),
        )


class FastAPINameCollisionTests(unittest.TestCase):
    def test_two_schemas_sharing_a_name_are_recorded_as_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "api.py").write_text("x = 1\n", encoding="utf-8")
            architecture = ProjectArchitecture(
                project_name="sample",
                project_path=str(root),
                endpoints=[EndpointInfo(
                    id="endpoint", http_method="POST", path="/users", function_name="create",
                    module="api", file_path=str(root / "api.py"), line_number=1, end_line_number=1,
                    request_schemas=["User"],
                )],
                schemas=[
                    SchemaInfo(id="schema-a", name="User", module="api.v1",
                               file_path=str(root / "api.py"), line_number=1, end_line_number=1),
                    SchemaInfo(id="schema-b", name="User", module="api.v2",
                               file_path=str(root / "api.py"), line_number=1, end_line_number=1),
                ],
            )

            result = ArchitectureGraphBuilder(include_language_graph=False).build_graph(architecture)

        body = next(edge for edge in result.edges if edge.relation == "REQUEST_BODY")
        self.assertEqual(body.to_id, "schema-a")
        self.assertEqual(body.candidates, ["schema-b"])
        self.assertEqual(str(body.resolution), str(Resolution.AMBIGUOUS))


if __name__ == "__main__":
    unittest.main()
