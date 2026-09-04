import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agent_view import (
    SCHEMA_VERSION,
    OccurrenceIndex,
    build_agent_view,
    build_derived_queries,
    build_exact_queries,
    build_framework_links,
    build_readable_nodes,
    default_profile_path,
    derive_terms,
    diff_agent_view,
    extract_clues,
    graph_to_dict,
    graph_to_json,
    list_repository_files,
    load_profile,
    scan_files,
)
from agent_view.exact_query import Clue
from agent_view.profile import Profile, ProfileError, Transform
from agent_view.models import ProfileRef, ReadableNode
from language_analyzers.core.cost import cost_for_text
from language_analyzers.core.graph_models import (
    Confidence,
    GraphEdge,
    GraphNode,
    NodeKind,
    RelationKind,
    Resolution,
    SourceSpan,
)

BASE_PROFILE_YAML = """
id: test.profile
version: 1
limits:
  max_arrival_nodes: 50
  min_term_length: 3
  max_file_bytes: 1048576
transforms:
  - id: split-case
  - id: token-adjacent-pairs
  - id: normalize-case
  - id: plural-singular
  - id: strip-affix
    prefixes:
      - get
    suffixes:
      - Service
"""


def make_profile(**overrides) -> Profile:
    values = {
        "ref": ProfileRef(id="test.profile", version=1, content_hash="0" * 64),
        "max_arrival_nodes": 50,
        "min_term_length": 3,
        "max_file_bytes": 1048576,
        "transforms": [
            Transform("split-case"),
            Transform("token-adjacent-pairs"),
            Transform("normalize-case"),
            Transform("plural-singular"),
            Transform("strip-affix", prefixes=["get"], suffixes=["Service"]),
        ],
        "include_agent_docs": True,
        "respect_gitignore": True,
    }
    values.update(overrides)
    return Profile(**values)


def symbol(node_id, path, start, end, label=None, kind=NodeKind.FUNCTION, symbol_path=""):
    return GraphNode(
        id=node_id,
        label=label if label is not None else node_id,
        group="symbol",
        category="symbol",
        kind=kind,
        symbol_path=symbol_path,
        span=SourceSpan(path, start, end),
    )


class TempDirFixture(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp()).resolve()

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def write(self, relative_path, source):
        path = self.directory / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        return path


class ProfileLoadingTests(TempDirFixture):
    def load(self, text, name="profile.yaml"):
        return load_profile(self.write(name, text))

    def test_shipped_default_profile_matches_contract(self):
        profile = load_profile(default_profile_path())

        self.assertEqual(profile.max_arrival_nodes, 50)
        self.assertEqual(profile.min_term_length, 3)
        self.assertEqual(profile.max_file_bytes, 1048576)
        self.assertEqual(
            [transform.id for transform in profile.transforms],
            ["split-case", "token-adjacent-pairs", "normalize-case", "plural-singular", "strip-affix"],
        )

    def test_content_hash_is_sha256_of_file_bytes(self):
        path = self.write("profile.yaml", BASE_PROFILE_YAML)

        profile = load_profile(path)

        self.assertEqual(
            profile.ref.content_hash,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )

    def test_missing_file_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            load_profile(self.directory / "absent.yaml")

    def test_unparsable_yaml_raises_profile_error(self):
        with self.assertRaises(ProfileError):
            self.load("id: [unterminated\n")

    def test_non_mapping_root_raises_profile_error(self):
        with self.assertRaises(ProfileError):
            self.load("- id: split-case\n")

    def test_missing_top_level_key_raises_profile_error(self):
        for key in ("id", "version", "limits", "transforms"):
            with self.subTest(key=key):
                lines = [line for line in BASE_PROFILE_YAML.strip().splitlines()]
                if key == "limits":
                    text = "\n".join(line for line in lines if not line.startswith("limits") and not line.startswith("  max") and not line.startswith("  min"))
                elif key == "transforms":
                    text = "\n".join(lines[:lines.index("transforms:")])
                else:
                    text = "\n".join(line for line in lines if not line.startswith(f"{key}:"))
                with self.assertRaises(ProfileError):
                    self.load(text)

    def test_non_int_version_raises_profile_error(self):
        with self.assertRaises(ProfileError):
            self.load(BASE_PROFILE_YAML.replace("version: 1", "version: '1'"))

    def test_missing_limit_key_raises_profile_error(self):
        with self.assertRaises(ProfileError):
            self.load(BASE_PROFILE_YAML.replace("  min_term_length: 3\n", ""))

    def test_non_int_limit_raises_profile_error(self):
        with self.assertRaises(ProfileError):
            self.load(BASE_PROFILE_YAML.replace("min_term_length: 3", "min_term_length: three"))

    def test_limit_below_one_raises_profile_error(self):
        with self.assertRaises(ProfileError):
            self.load(BASE_PROFILE_YAML.replace("min_term_length: 3", "min_term_length: 0"))

    def test_transforms_not_a_list_raises_profile_error(self):
        text = BASE_PROFILE_YAML[:BASE_PROFILE_YAML.index("transforms:")] + "transforms: split-case\n"
        with self.assertRaises(ProfileError):
            self.load(text)

    def test_empty_transforms_raises_profile_error(self):
        text = BASE_PROFILE_YAML[:BASE_PROFILE_YAML.index("transforms:")] + "transforms: []\n"
        with self.assertRaises(ProfileError):
            self.load(text)

    def test_unknown_transform_id_raises_profile_error_naming_the_id(self):
        text = BASE_PROFILE_YAML[:BASE_PROFILE_YAML.index("transforms:")] + "transforms:\n  - id: stemming\n"
        with self.assertRaises(ProfileError) as raised:
            self.load(text)
        self.assertIn("stemming", str(raised.exception))

    def test_duplicate_transform_id_raises_profile_error(self):
        text = (
            BASE_PROFILE_YAML[:BASE_PROFILE_YAML.index("transforms:")]
            + "transforms:\n  - id: split-case\n  - id: split-case\n"
        )
        with self.assertRaises(ProfileError):
            self.load(text)

    def test_strip_affix_without_affixes_raises_profile_error(self):
        text = BASE_PROFILE_YAML[:BASE_PROFILE_YAML.index("transforms:")] + "transforms:\n  - id: strip-affix\n"
        with self.assertRaises(ProfileError):
            self.load(text)

    def test_affixes_on_other_transform_raise_profile_error(self):
        text = (
            BASE_PROFILE_YAML[:BASE_PROFILE_YAML.index("transforms:")]
            + "transforms:\n  - id: split-case\n    prefixes: [get]\n"
        )
        with self.assertRaises(ProfileError):
            self.load(text)


class ScanTests(TempDirFixture):
    def scan(self, paths, contents, *, max_file_bytes=1048576, include_agent_docs=True):
        def reader(path):
            return contents.get(Path(path).relative_to(self.directory).as_posix())

        return scan_files(
            self.directory, paths,
            max_file_bytes=max_file_bytes, reader=reader, include_agent_docs=include_agent_docs,
        )

    def test_git_repository_lists_tracked_files_only(self):
        self.write("tracked.py", "x = 1\n")
        self.write("untracked.py", "y = 2\n")
        import subprocess
        subprocess.run(["git", "init", "-q"], cwd=self.directory, check=True)
        subprocess.run(["git", "add", "tracked.py"], cwd=self.directory, check=True)

        source, paths = list_repository_files(self.directory)

        self.assertEqual(source, "git")
        self.assertEqual(paths, ["tracked.py"])

    def test_non_repository_falls_back_to_static_walk(self):
        self.write("pkg/module.py", "x = 1\n")
        self.write("node_modules/skipped.js", "x\n")
        self.write(".hidden/skipped.py", "x\n")
        self.write("build/skipped.py", "x\n")
        for directory in ("venv", "env", "__pycache__", "dist"):
            self.write(f"{directory}/skipped.py", "x\n")

        source, paths = list_repository_files(self.directory)

        self.assertEqual(source, "static_fallback")
        self.assertEqual(paths, ["pkg/module.py"])

    def test_binary_file_is_excluded(self):
        included, excluded, contents = self.scan(["blob.bin"], {"blob.bin": "abc\x00def"})

        self.assertEqual(included, [])
        self.assertEqual([(item.file_path, item.reason) for item in excluded], [("blob.bin", "binary")])
        self.assertEqual(contents, {})

    def test_nul_after_the_sniff_window_is_not_binary(self):
        text = "a" * 8192 + "\x00tail"

        included, excluded, contents = self.scan(["late.py"], {"late.py": text})

        self.assertEqual(included, ["late.py"])
        self.assertEqual(excluded, [])
        self.assertEqual(contents["late.py"], text)

    def test_nul_at_the_last_sniffed_byte_is_binary(self):
        included, excluded, _ = self.scan(["edge.py"], {"edge.py": "a" * 8191 + "\x00tail"})

        self.assertEqual(included, [])
        self.assertEqual([item.reason for item in excluded], ["binary"])

    def test_size_is_checked_before_binary_sniffing(self):
        _, excluded, _ = self.scan(["blob.bin"], {"blob.bin": "\x00" * 100}, max_file_bytes=10)

        self.assertEqual([item.reason for item in excluded], ["too_large"])

    def test_unreadable_file_is_excluded(self):
        _, excluded, _ = self.scan(["gone.py"], {})

        self.assertEqual([(item.file_path, item.reason) for item in excluded], [("gone.py", "unreadable")])

    def test_generated_vendored_and_test_paths_are_scanned_not_excluded(self):
        paths = ["migrations/0001.py", "vendor/lib.py", "tests/test_x.py"]
        included, excluded, _ = self.scan(paths, {path: "x = 1\n" for path in paths})

        self.assertEqual(included, sorted(paths))
        self.assertEqual(excluded, [])

    def test_agent_docs_are_dropped_without_an_exclusion_record(self):
        paths = ["AGENTS.md", "CLAUDE.md", "README.md", "main.py"]
        included, excluded, _ = self.scan(
            paths, {path: "text\n" for path in paths}, include_agent_docs=False
        )

        self.assertEqual(included, ["main.py"])
        self.assertEqual(excluded, [])


class ReadableNodeTests(unittest.TestCase):
    def test_spanless_nodes_produce_no_readable_node(self):
        package = GraphNode(id="pkg", label="pkg", group="package", category="package", kind=NodeKind.PACKAGE)

        nodes, _ = build_readable_nodes([package], ["a.py"], {"a.py": "x = 1\n"})

        self.assertEqual([node.id for node in nodes], ["file:a.py"])

    def test_nodes_outside_the_scan_are_dropped(self):
        nodes, _ = build_readable_nodes([symbol("s", "other.py", 1, 2)], ["a.py"], {"a.py": "x = 1\n"})

        self.assertEqual([node.id for node in nodes], ["file:a.py"])

    def test_symbols_in_one_file_share_the_whole_file_read_cost(self):
        text = "def a():\n    pass\n\n\ndef b():\n    pass\n"

        nodes, by_file = build_readable_nodes(
            [symbol("a", "m.py", 1, 2), symbol("b", "m.py", 5, 6)], ["m.py"], {"m.py": text}
        )

        self.assertEqual({node.read_cost for node in nodes}, {cost_for_text(text)})
        self.assertEqual(by_file["m.py"], ["a", "b"])

    def test_file_without_symbols_gets_a_file_node(self):
        nodes, _ = build_readable_nodes([], ["docs/readme.md"], {"docs/readme.md": "hi\n"})

        node = nodes[0]
        self.assertEqual(
            (node.id, node.symbol_id, node.kind, node.start_line, node.end_line),
            ("file:docs/readme.md", None, "file", None, None),
        )

    def test_empty_file_keeps_the_cost_model_result(self):
        nodes, _ = build_readable_nodes([], ["empty.py"], {"empty.py": ""})

        self.assertEqual(nodes[0].read_cost, cost_for_text(""))

    def test_duplicate_ids_keep_the_first_after_sorting(self):
        first = symbol("dup", "m.py", 1, 2, label="first")
        second = symbol("dup", "m.py", 5, 6, label="second")

        reversed_input, _ = build_readable_nodes(
            [second, first], ["m.py"], {"m.py": "a\nb\nc\nd\ne\nf\n"})
        forward_input, _ = build_readable_nodes(
            [first, second], ["m.py"], {"m.py": "a\nb\nc\nd\ne\nf\n"})

        self.assertEqual([(node.id, node.label) for node in reversed_input], [("dup", "first")])
        self.assertEqual(
            [(node.id, node.label) for node in forward_input],
            [(node.id, node.label) for node in reversed_input],
        )

    def test_flags_come_from_the_path_not_the_graph_node(self):
        node = symbol("t", "tests/test_x.py", 1, 2)
        node.flags = ["generated"]

        nodes, _ = build_readable_nodes([node], ["tests/test_x.py"], {"tests/test_x.py": "x = 1\n"})

        self.assertEqual(nodes[0].flags, ["test"])


class OccurrenceTests(unittest.TestCase):
    def index(self, contents, nodes=()):
        by_file = {}
        for node in nodes:
            by_file.setdefault(node.file_path, []).append(node)
        for path in contents:
            by_file.setdefault(path, [])
        return OccurrenceIndex(contents, by_file)

    def readable(self, node_id, path, start=None, end=None):
        return ReadableNode(
            id=node_id, file_path=path, symbol_id=node_id if start else None,
            label=node_id, kind="function" if start else "file",
            start_line=start, end_line=end, read_cost=cost_for_text(""), flags=[],
        )

    def test_word_boundary_match_is_case_sensitive(self):
        index = self.index({"m.py": "user\nuser_id\nxuser\nUser\n"}, [self.readable("file:m.py", "m.py")])

        found = index.find("user")

        self.assertEqual([(item.line, item.col) for item in found], [(1, 0)])

    def test_empty_term_returns_no_occurrences(self):
        index = self.index({"m.py": "user\n"}, [self.readable("file:m.py", "m.py")])

        self.assertEqual(index.find(""), [])

    def test_smallest_enclosing_span_wins(self):
        index = self.index(
            {"m.py": "class A:\n    def b(self):\n        user\n"},
            [self.readable("outer", "m.py", 1, 3), self.readable("inner", "m.py", 2, 3)],
        )

        self.assertEqual(index.find("user")[0].enclosing_node_id, "inner")

    def test_equal_width_spans_break_ties_by_lowest_id(self):
        index = self.index(
            {"m.py": "user\n"},
            [self.readable("bbb", "m.py", 1, 1), self.readable("aaa", "m.py", 1, 1)],
        )

        self.assertEqual(index.find("user")[0].enclosing_node_id, "aaa")

    def test_uncovered_line_falls_back_to_the_file_node(self):
        index = self.index(
            {"m.py": "header\nuser\n"},
            [self.readable("file:m.py", "m.py"), self.readable("sym", "m.py", 1, 1)],
        )

        self.assertEqual(index.find("user")[0].enclosing_node_id, "file:m.py")

    def test_uncovered_line_without_file_node_uses_lowest_symbol_id(self):
        index = self.index(
            {"m.py": "header\nuser\n"},
            [self.readable("zzz", "m.py", 1, 1), self.readable("aaa", "m.py", 1, 1)],
        )

        self.assertEqual(index.find("user")[0].enclosing_node_id, "aaa")

    def test_context_is_derived_from_extension_and_syntax(self):
        contents = {
            "notes.md": "user\n",
            "notes.rst": "user\n",
            "notes.txt": "user\n",
            "settings.yaml": "user: 1\n",
            "settings.json": '{"user": 1}\n',
            "app.py": 'user = 1\n# user comment\n"""\nuser doc\n"""\n',
            "app.ts": "let x = 1; // user\n/* user */\n",
        }
        index = self.index(contents, [self.readable(f"file:{path}", path) for path in contents])

        contexts = {(item.file_path, item.line): item.context for item in index.find("user")}

        self.assertEqual(contexts[("notes.md", 1)], "doc")
        self.assertEqual(contexts[("notes.rst", 1)], "doc")
        self.assertEqual(contexts[("notes.txt", 1)], "doc")
        self.assertEqual(contexts[("settings.yaml", 1)], "config")
        self.assertEqual(contexts[("settings.json", 1)], "config")
        self.assertEqual(contexts[("app.py", 1)], "code")
        self.assertEqual(contexts[("app.py", 2)], "comment")
        self.assertEqual(contexts[("app.py", 4)], "docstring")
        self.assertEqual(contexts[("app.ts", 1)], "comment")
        self.assertEqual(contexts[("app.ts", 2)], "comment")

    def test_occurrences_are_sorted_by_path_line_and_column(self):
        index = self.index(
            {"b.py": "user user\n", "a.py": "\nuser\n"},
            [self.readable("file:a.py", "a.py"), self.readable("file:b.py", "b.py")],
        )

        found = index.find("user")

        self.assertEqual(
            [(item.file_path, item.line, item.col) for item in found],
            [("a.py", 2, 0), ("b.py", 1, 0), ("b.py", 1, 5)],
        )

    def test_index_never_reads_from_disk(self):
        index = self.index({"missing/from/disk.py": "user\n"}, [self.readable("file:missing/from/disk.py", "missing/from/disk.py")])

        self.assertEqual(len(index.find("user")), 1)


class ClueExtractionTests(unittest.TestCase):
    def extract(self, nodes, contents, profile=None):
        profile = profile or make_profile()
        readable, by_file = build_readable_nodes(nodes, list(contents), contents)
        return extract_clues(nodes, readable, contents, profile), readable

    def test_every_clue_kind_is_extracted(self):
        contents = {
            "app.py": 'ROUTE = "/users/list"\nMESSAGE = "boom happened"\n\n\ndef handler():\n    raise ValueError("broken thing")\n',
            "settings.yaml": "database_url: postgres\n",
            "notes.md": "see `handler` for details\n",
        }
        nodes = [symbol("handler", "app.py", 5, 6, label="handler", symbol_path="app.handler")]

        clues, _ = self.extract(nodes, contents)

        self.assertIn("identifier", clues["handler"].clue_kinds)
        self.assertIn("doc_mention", clues["handler"].clue_kinds)
        self.assertIn("qualified_name", clues["app.handler"].clue_kinds)
        self.assertIn("literal", clues["/users/list"].clue_kinds)
        self.assertIn("route", clues["/users/list"].clue_kinds)
        self.assertIn("error_message", clues["broken thing"].clue_kinds)
        self.assertIn("config_key", clues["database_url"].clue_kinds)
        self.assertIn("path", clues["app.py"].clue_kinds)
        self.assertIn("path", clues["app"].clue_kinds)

    def test_short_terms_are_dropped(self):
        clues, _ = self.extract([symbol("id", "app.py", 1, 1, label="id")], {"app.py": "id = 1\n"})

        self.assertNotIn("id", clues)

    def test_terms_with_newlines_are_dropped(self):
        node = symbol("weird", "app.py", 1, 1, label="line\nbreak")

        clues, _ = self.extract([node], {"app.py": "x = 1\n"})

        self.assertNotIn("line\nbreak", clues)

    def test_one_term_seen_twice_merges_into_one_clue(self):
        contents = {"app.py": 'handler = "handler"\n', "notes.md": "`handler`\n"}
        nodes = [symbol("handler", "app.py", 1, 1, label="handler")]

        clues, _ = self.extract(nodes, contents)

        self.assertEqual(sorted(clues["handler"].clue_kinds), ["doc_mention", "identifier", "literal"])

    def test_surrounding_whitespace_is_stripped_before_the_length_check(self):
        contents = {"app.py": 'x = "  ab  "\ny = "  handler  "\n'}

        clues, _ = self.extract([], contents)

        self.assertNotIn("  ab  ", clues)
        self.assertIn("handler", clues)


class ExactQueryTests(unittest.TestCase):
    def build(self, contents, nodes, profile=None):
        profile = profile or make_profile()
        readable, by_file = build_readable_nodes(nodes, list(contents), contents)
        grouped = {}
        for node in readable:
            grouped.setdefault(node.file_path, []).append(node)
        index = OccurrenceIndex(contents, grouped)
        clues = extract_clues(nodes, readable, contents, profile)
        return build_exact_queries(clues, index, profile), index, clues, profile

    def test_terms_without_occurrences_produce_no_query(self):
        profile = make_profile()
        index = OccurrenceIndex({"app.py": "x = 1\n"}, {"app.py": []})
        clue = Clue(term="absent_term", clue_kinds={"identifier"}, origin_node_ids=set())

        self.assertEqual(build_exact_queries({"absent_term": clue}, index, profile), [])

    def _query_with_arrivals(self, count):
        profile = make_profile()
        contents = {f"f{position:03d}.py": "target\n" for position in range(count)}
        grouped = {path: [] for path in contents}
        readable = []
        for path in contents:
            node = ReadableNode(
                id=f"file:{path}", file_path=path, symbol_id=None, label=path, kind="file",
                start_line=None, end_line=None, read_cost=cost_for_text("target\n"), flags=[],
            )
            grouped[path] = [node]
            readable.append(node)
        index = OccurrenceIndex(contents, grouped)
        clue = Clue(term="target", clue_kinds={"identifier"}, origin_node_ids=set())
        return build_exact_queries({"target": clue}, index, profile)[0]

    def test_arrival_count_at_the_limit_is_not_excluded(self):
        query = self._query_with_arrivals(50)

        self.assertEqual(len(query.arrival_node_ids), 50)
        self.assertFalse(query.excluded)
        self.assertIsNone(query.exclusion_reason)

    def test_arrival_count_above_the_limit_is_excluded(self):
        query = self._query_with_arrivals(51)

        self.assertTrue(query.excluded)
        self.assertEqual(query.exclusion_reason, "too_many_arrival_nodes")

    def test_excluded_queries_still_record_all_occurrences_and_output_tokens(self):
        query = self._query_with_arrivals(51)

        self.assertEqual(len(query.occurrences), 51)
        self.assertEqual(query.output_tokens, 217)

    def test_output_tokens_use_the_occurrence_render(self):
        from language_analyzers.core.cost import estimate_tokens

        queries, _, _, _ = self.build({"app.py": "handler\n"}, [symbol("handler", "app.py", 1, 1, label="handler")])
        query = next(item for item in queries if item.term == "handler")

        self.assertEqual(
            query.output_tokens,
            estimate_tokens("\n".join(f"{o.file_path}:{o.line}:{o.matched_text}" for o in query.occurrences)),
        )

    def test_query_id_is_the_documented_digest(self):
        queries, _, _, profile = self.build({"app.py": "handler\n"}, [symbol("handler", "app.py", 1, 1, label="handler")])
        query = next(item for item in queries if item.term == "handler")

        self.assertEqual(
            query.id,
            hashlib.sha256(f"exact|handler|{profile.ref.version}".encode("utf-8")).hexdigest()[:16],
        )


class DerivedQueryTests(unittest.TestCase):
    def test_each_transform_produces_its_documented_terms(self):
        profile = make_profile()

        self.assertEqual(
            derive_terms("getUserName", profile),
            [
                ("get", "split-case"),
                ("User", "split-case"),
                ("Name", "split-case"),
                ("getUser", "token-adjacent-pairs"),
                ("UserName", "token-adjacent-pairs"),
                ("getusername", "normalize-case"),
                ("getUserNames", "plural-singular"),
                ("userName", "strip-affix"),
            ],
        )

    def test_plural_singular_covers_each_documented_branch(self):
        profile = make_profile()
        derived = {identifier: dict(derive_terms(identifier, profile)) for identifier in
                   ("Entries", "Widgets", "address", "Policy", "Delay")}

        self.assertIn("Entry", derived["Entries"])
        self.assertIn("Widget", derived["Widgets"])
        self.assertIn("addresss", derived["address"])
        self.assertIn("Policies", derived["Policy"])
        self.assertIn("Delays", derived["Delay"])

    def test_terms_shorter_than_the_minimum_are_dropped(self):
        profile = make_profile(min_term_length=5)

        self.assertNotIn("User", dict(derive_terms("getUserName", profile)))

    def test_a_transform_result_equal_to_the_source_is_dropped(self):
        profile = make_profile()

        self.assertNotIn("handler", dict(derive_terms("handler", profile)))

    def test_the_first_transform_in_declaration_order_owns_a_shared_term(self):
        profile = make_profile()

        self.assertEqual(dict(derive_terms("user_name", profile))["username"], "token-adjacent-pairs")

    def test_no_query_is_created_when_the_derived_term_has_no_occurrence(self):
        profile = make_profile()
        contents = {"app.py": "getUserName = 1\n"}
        grouped = {"app.py": []}
        index = OccurrenceIndex(contents, grouped)
        clues = {"getUserName": Clue(term="getUserName", clue_kinds={"identifier"}, origin_node_ids={"n1"})}

        derived = build_derived_queries(clues, index, profile, {})

        self.assertEqual(derived, [])

    def test_a_derived_term_matching_an_exact_query_merges_into_it(self):
        profile = make_profile()
        contents = {"app.py": "getUserName = 1\nUser = 2\n"}
        node = ReadableNode(
            id="file:app.py", file_path="app.py", symbol_id=None, label="app.py", kind="file",
            start_line=None, end_line=None, read_cost=cost_for_text(contents["app.py"]), flags=[],
        )
        index = OccurrenceIndex(contents, {"app.py": [node]})
        clues = {"getUserName": Clue(term="getUserName", clue_kinds={"identifier"}, origin_node_ids={"origin-1"})}
        exact_clue = Clue(term="User", clue_kinds={"identifier"}, origin_node_ids={"origin-2"})
        existing = {"User": build_exact_queries({"User": exact_clue}, index, profile)[0]}

        derived = build_derived_queries(clues, index, profile, existing)

        self.assertNotIn("User", [query.term for query in derived])
        self.assertEqual(existing["User"].origin_node_ids, ["origin-1", "origin-2"])
        self.assertEqual(existing["User"].source_terms, ["getUserName"])
        self.assertEqual(existing["User"].clue_kinds, ["identifier"])

    def test_derived_queries_use_the_same_arrival_limit(self):
        profile = make_profile(max_arrival_nodes=1)
        contents = {"a.py": "getUserName\nUser\n", "b.py": "User\n"}
        grouped = {}
        for path, text in contents.items():
            grouped[path] = [ReadableNode(
                id=f"file:{path}", file_path=path, symbol_id=None, label=path, kind="file",
                start_line=None, end_line=None, read_cost=cost_for_text(text), flags=[],
            )]
        index = OccurrenceIndex(contents, grouped)
        clues = {"getUserName": Clue(term="getUserName", clue_kinds={"identifier"}, origin_node_ids=set())}

        derived = build_derived_queries(clues, index, profile, {})
        query = next(item for item in derived if item.term == "User")

        self.assertTrue(query.excluded)
        self.assertEqual(query.exclusion_reason, "too_many_arrival_nodes")
        self.assertEqual(query.rule_id, "split-case")
        self.assertEqual(query.source_terms, ["getUserName"])

    def test_derived_arrival_count_at_the_limit_is_not_excluded(self):
        profile = make_profile(max_arrival_nodes=2)
        contents = {"a.py": "getUserName\nUser\n", "b.py": "User\n"}
        grouped = {}
        for path, text in contents.items():
            grouped[path] = [ReadableNode(
                id=f"file:{path}", file_path=path, symbol_id=None, label=path, kind="file",
                start_line=None, end_line=None, read_cost=cost_for_text(text), flags=[],
            )]
        index = OccurrenceIndex(contents, grouped)
        clues = {"getUserName": Clue(term="getUserName", clue_kinds={"identifier"}, origin_node_ids=set())}

        derived = build_derived_queries(clues, index, profile, {})
        query = next(item for item in derived if item.term == "User")

        self.assertEqual(len(query.arrival_node_ids), 2)
        self.assertFalse(query.excluded)
        self.assertIsNone(query.exclusion_reason)


class FrameworkLinkTests(unittest.TestCase):
    def setUp(self):
        self.profile = make_profile()
        contents = {"a.py": "alpha\n", "b.py": "beta\n"}
        self.readable_by_id = {}
        grouped = {}
        for path, text in contents.items():
            node = ReadableNode(
                id=f"sym:{path}", file_path=path, symbol_id=f"sym:{path}", label=path, kind="function",
                start_line=1, end_line=1, read_cost=cost_for_text(text), flags=[],
            )
            self.readable_by_id[node.id] = node
            grouped[path] = [node]
        self.index = OccurrenceIndex(contents, grouped)

    def edge(self, to_id, rule=None, evidence=None):
        return GraphEdge(
            from_id="endpoint", to_id=to_id, relation=RelationKind.IMPLEMENTED_BY,
            confidence=Confidence.FRAMEWORK_INFERRED, resolution=Resolution.UNIQUE_NAME,
            evidence=evidence,
            metadata={"framework_rule": rule} if rule else {},
        )

    def build(self, edges):
        return build_framework_links(edges, self.readable_by_id, self.index, self.profile)

    def test_non_framework_edges_are_ignored(self):
        edge = GraphEdge(from_id="endpoint", to_id="sym:a.py", relation=RelationKind.CALLS)

        links, queries, unknown = self.build([edge])

        self.assertEqual((links, queries, unknown), ([], [], []))

    def test_missing_rule_metadata_is_reported_as_unknown(self):
        links, queries, unknown = self.build([self.edge("sym:a.py")])

        self.assertEqual(links, [])
        self.assertEqual(unknown, ["endpoint->sym:a.py"])

    def test_invalid_specificity_is_reported_as_unknown(self):
        links, _, unknown = self.build([self.edge("sym:a.py", {"id": "r1", "specificity": "maybe"})])

        self.assertEqual(links, [])
        self.assertEqual(unknown, ["endpoint->sym:a.py"])

    def test_unique_rules_produce_a_single_target_and_no_query(self):
        links, queries, _ = self.build([self.edge("sym:a.py", {"id": "r1", "specificity": "unique"})])

        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].to_node_ids, ["sym:a.py"])
        self.assertIsNone(links[0].query_id)
        self.assertEqual(queries, [])

    def test_narrowing_rules_group_into_one_link_with_a_query(self):
        edges = [
            self.edge("sym:a.py", {"id": "r2", "specificity": "narrowing"}),
            self.edge("sym:b.py", {"id": "r2", "specificity": "narrowing"}),
        ]

        links, queries, _ = self.build(edges)

        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].to_node_ids, ["sym:a.py", "sym:b.py"])
        self.assertEqual(len(queries), 1)
        self.assertEqual(
            queries[0].id,
            hashlib.sha256(f"framework|endpoint|r2|{self.profile.ref.version}".encode("utf-8")).hexdigest()[:16],
        )
        self.assertEqual(links[0].query_id, queries[0].id)
        self.assertEqual((queries[0].kind, queries[0].term), ("framework", "r2"))
        self.assertEqual(queries[0].arrival_node_ids, ["sym:a.py", "sym:b.py"])

    def test_targets_outside_readable_are_dropped_and_empty_links_disappear(self):
        edges = [
            self.edge("sym:a.py", {"id": "r2", "specificity": "narrowing"}),
            self.edge("absent", {"id": "r2", "specificity": "narrowing"}),
        ]

        links, _, unknown = self.build(edges)

        self.assertEqual(links[0].to_node_ids, ["sym:a.py"])
        self.assertEqual(unknown, [])

        links, _, _ = self.build([self.edge("absent", {"id": "r3", "specificity": "unique"})])
        self.assertEqual(links, [])

    def test_evidence_falls_back_when_the_edge_carries_none(self):
        with_evidence = self.edge("sym:a.py", {"id": "r1", "specificity": "unique"}, SourceSpan("a.py", 7, 7))
        without = self.edge("sym:b.py", {"id": "r4", "specificity": "unique"})

        links, _, _ = self.build([with_evidence, without])
        by_rule = {link.rule_id: link for link in links}

        self.assertEqual((by_rule["r1"].evidence_file, by_rule["r1"].evidence_line), ("a.py", 7))
        self.assertEqual((by_rule["r4"].evidence_file, by_rule["r4"].evidence_line), ("<framework-inference>", 1))


class Architecture(SimpleNamespace):
    pass


class GraphBuildingTests(TempDirFixture):
    def architecture(self, nodes, edges=()):
        return Architecture(
            project_name="demo",
            project_path=str(self.directory),
            nodes=list(nodes),
            edges=list(edges),
        )

    def build(self, contents, nodes, edges=(), profile=None, order=None):
        paths = order if order is not None else sorted(contents)

        def lister(_root):
            return "static_fallback", list(paths)

        def reader(path):
            return contents.get(Path(path).relative_to(self.directory).as_posix())

        return build_agent_view(
            self.architecture(nodes, edges),
            profile=profile or make_profile(),
            file_reader=reader,
            file_lister=lister,
        )

    def test_graph_serialization_omits_project_path_and_keeps_top_level_keys(self):
        graph = self.build({"app.py": "handler = 1\n"}, [symbol("handler", "app.py", 1, 1, label="handler")])

        payload = graph_to_dict(graph)

        self.assertEqual(
            sorted(payload),
            ["framework_links", "profile", "project_name", "query_nodes",
             "readable_nodes", "scan", "schema_version", "unreachable_node_ids"],
        )
        self.assertNotIn("project_path", graph_to_json(graph))
        self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
        self.assertEqual(
            sorted(payload["readable_nodes"][0]["read_cost"]),
            ["char_count", "line_count", "token_estimate"],
        )

    def test_json_is_indented_sorted_and_newline_terminated(self):
        graph = self.build({"app.py": "handler = 1\n"}, [symbol("handler", "app.py", 1, 1, label="handler")])

        text = graph_to_json(graph)

        self.assertTrue(text.endswith("}\n"))
        self.assertIn('\n  "framework_links"', text)
        self.assertLess(text.index('"project_name"'), text.index('"query_nodes"'))

    def test_unreachable_nodes_exclude_arrivals_of_live_queries(self):
        contents = {"app.py": "handler = 1\n", "orphan.py": "\n"}

        graph = self.build(contents, [symbol("handler", "app.py", 1, 1, label="handler")])

        self.assertIn("file:orphan.py", graph.unreachable_node_ids)
        self.assertNotIn("handler", graph.unreachable_node_ids)

    def test_reaching_one_symbol_reaches_every_symbol_in_its_file(self):
        contents = {"app.py": "handler = 1\nid = 2\n", "orphan.py": "\n"}
        nodes = [
            symbol("handler", "app.py", 1, 1, label="handler"),
            symbol("short", "app.py", 2, 2, label="id"),
        ]

        graph = self.build(contents, nodes)

        arrivals = [
            node_id
            for query in graph.query_nodes if not query.excluded
            for node_id in query.arrival_node_ids
        ]
        self.assertNotIn("short", arrivals)
        self.assertNotIn("short", graph.unreachable_node_ids)
        self.assertIn("file:orphan.py", graph.unreachable_node_ids)

    def test_excluded_query_arrivals_do_not_count_as_reached(self):
        contents = {"a.py": "shared = 1\n", "b.py": "shared = 2\n"}
        nodes = [
            symbol("a-shared", "a.py", 1, 1, label="shared"),
            symbol("b-shared", "b.py", 1, 1, label="shared"),
        ]

        permissive = self.build(contents, nodes)
        restricted = self.build(contents, nodes, profile=make_profile(max_arrival_nodes=1))

        self.assertEqual(permissive.unreachable_node_ids, [])
        self.assertEqual(restricted.unreachable_node_ids, ["a-shared", "b-shared"])

    def test_framework_link_targets_count_as_reached(self):
        contents = {"a.py": "alpha = 1\n", "b.py": "zz = 2\n"}
        nodes = [
            symbol("alpha", "a.py", 1, 1, label="alpha"),
            symbol("zz", "b.py", 1, 1, label="zz"),
        ]
        edge = GraphEdge(
            from_id="alpha", to_id="zz", relation=RelationKind.IMPLEMENTED_BY,
            confidence=Confidence.FRAMEWORK_INFERRED,
            metadata={"framework_rule": {"id": "demo.rule", "specificity": "unique"}},
        )

        without_link = self.build(contents, nodes)
        with_link = self.build(contents, nodes, edges=[edge])

        self.assertEqual(without_link.unreachable_node_ids, ["zz"])
        self.assertEqual(with_link.unreachable_node_ids, [])

    def test_building_twice_produces_byte_identical_json(self):
        contents = {"app.py": "handler = 1\n", "pkg/service.py": "class UserService:\n    pass\n"}
        nodes = [
            symbol("handler", "app.py", 1, 1, label="handler"),
            symbol("UserService", "pkg/service.py", 1, 2, label="UserService", kind=NodeKind.CLASS),
        ]

        first = graph_to_json(self.build(contents, nodes))
        second = graph_to_json(self.build(contents, nodes))

        self.assertEqual(first, second)

    def test_reversed_file_listing_produces_identical_json(self):
        contents = {"app.py": "handler = 1\n", "pkg/service.py": "class UserService:\n    pass\n"}
        nodes = [
            symbol("handler", "app.py", 1, 1, label="handler"),
            symbol("UserService", "pkg/service.py", 1, 2, label="UserService", kind=NodeKind.CLASS),
        ]

        forward = graph_to_json(self.build(contents, nodes, order=sorted(contents)))
        backward = graph_to_json(self.build(contents, nodes, order=sorted(contents, reverse=True)))

        self.assertEqual(forward, backward)

    def test_scan_report_records_source_counts_and_exclusions(self):
        contents = {"app.py": "handler = 1\n", "blob.bin": "\x00\x00"}

        graph = self.build(contents, [])

        self.assertEqual(graph.scan.ignore_source, "static_fallback")
        self.assertEqual(graph.scan.scanned_file_count, 1)
        self.assertEqual(
            [(item.file_path, item.reason) for item in graph.scan.excluded_files],
            [("blob.bin", "binary")],
        )


class DiffTests(TempDirFixture):
    def build(self, contents, nodes, edges=()):
        def lister(_root):
            return "static_fallback", sorted(contents)

        def reader(path):
            return contents.get(Path(path).relative_to(self.directory).as_posix())

        architecture = Architecture(
            project_name="demo", project_path=str(self.directory),
            nodes=list(nodes), edges=list(edges),
        )
        return graph_to_dict(build_agent_view(
            architecture, profile=make_profile(), file_reader=reader, file_lister=lister,
        ))

    def test_diff_reports_added_removed_and_changed_readable_nodes(self):
        before = self.build({"app.py": "handler = 1\n"}, [symbol("handler", "app.py", 1, 1, label="handler")])
        after = self.build(
            {"app.py": "handler = 1\nextra = 2\n", "new.py": "x = 1\n"},
            [symbol("handler", "app.py", 1, 2, label="handler")],
        )

        result = diff_agent_view(before, after)

        self.assertEqual(result["schema_version"], SCHEMA_VERSION)
        self.assertEqual(result["readable_nodes"]["added"], ["file:new.py"])
        self.assertEqual(result["readable_nodes"]["removed"], [])
        changed = {entry["id"]: entry["fields"] for entry in result["readable_nodes"]["changed"]}
        self.assertEqual(
            sorted(changed["handler"]),
            ["end_line", "read_cost.token_estimate"],
        )
        self.assertEqual(changed["handler"]["end_line"], {"before": 1, "after": 2})

    def test_profile_section_is_always_present(self):
        graph = self.build({"app.py": "handler = 1\n"}, [])

        result = diff_agent_view(graph, graph)

        self.assertEqual(result["profile"], {"before": graph["profile"], "after": graph["profile"]})
        self.assertEqual(result["query_nodes"]["changed"], [])
        self.assertEqual(result["framework_links"], {"added": [], "removed": [], "changed": []})

    def test_query_node_changes_and_removals_are_reported(self):
        before = self.build(
            {"a.py": "alpha = 1\n", "b.py": "gone = 2\n"},
            [symbol("alpha", "a.py", 1, 1, label="alpha"), symbol("gone", "b.py", 1, 1, label="gone")],
        )
        after = self.build(
            {"a.py": "alpha = 1\nalpha = 3\n", "b.py": "\n"},
            [symbol("alpha", "a.py", 1, 2, label="alpha")],
        )

        result = diff_agent_view(before, after)

        before_terms = {node["id"]: node["term"] for node in before["query_nodes"]}
        after_terms = {node["id"]: node["term"] for node in after["query_nodes"]}
        self.assertEqual(
            [before_terms[identifier] for identifier in result["query_nodes"]["removed"]],
            ["gone"],
        )
        self.assertEqual(result["query_nodes"]["added"], [])
        changed = {before_terms[entry["id"]]: entry["fields"] for entry in result["query_nodes"]["changed"]}
        self.assertEqual(sorted(changed["alpha"]), ["output_tokens"])
        self.assertLess(
            changed["alpha"]["output_tokens"]["before"],
            changed["alpha"]["output_tokens"]["after"],
        )
        self.assertNotIn("gone", after_terms.values())

    def test_unique_links_from_one_source_keep_separate_identities(self):
        contents = {"a.py": "alpha = 1\n", "b.py": "beta = 2\n", "c.py": "gamma = 3\n"}
        nodes = [
            symbol("alpha", "a.py", 1, 1, label="alpha"),
            symbol("beta", "b.py", 1, 1, label="beta"),
            symbol("gamma", "c.py", 1, 1, label="gamma"),
        ]

        def edge(to_id):
            return GraphEdge(
                from_id="alpha", to_id=to_id, relation=RelationKind.IMPLEMENTED_BY,
                confidence=Confidence.FRAMEWORK_INFERRED,
                metadata={"framework_rule": {"id": "demo.rule", "specificity": "unique"}},
            )

        before = self.build(contents, nodes, [edge("beta"), edge("gamma")])
        after = self.build(contents, nodes, [edge("beta")])

        self.assertEqual(
            [link["id"] for link in before["framework_links"]],
            ["alpha|demo.rule|beta", "alpha|demo.rule|gamma"],
        )
        result = diff_agent_view(before, after)
        self.assertEqual(result["framework_links"]["removed"], ["alpha|demo.rule|gamma"])
        self.assertEqual(result["framework_links"]["changed"], [])

    def test_framework_link_removal_is_reported(self):
        contents = {"a.py": "alpha = 1\n", "b.py": "beta = 2\n"}
        nodes = [symbol("alpha", "a.py", 1, 1, label="alpha"), symbol("beta", "b.py", 1, 1, label="beta")]
        edge = GraphEdge(
            from_id="alpha", to_id="beta", relation=RelationKind.IMPLEMENTED_BY,
            confidence=Confidence.FRAMEWORK_INFERRED,
            metadata={"framework_rule": {"id": "demo.rule", "specificity": "unique"}},
        )

        result = diff_agent_view(self.build(contents, nodes, [edge]), self.build(contents, nodes))

        self.assertEqual(result["framework_links"]["removed"], ["alpha|demo.rule|beta"])
        self.assertEqual(result["framework_links"]["added"], [])
        self.assertEqual(result["framework_links"]["changed"], [])

    def test_framework_link_changes_are_reported(self):
        contents = {"a.py": "alpha = 1\n", "b.py": "beta = 2\n"}
        nodes = [symbol("alpha", "a.py", 1, 1, label="alpha"), symbol("beta", "b.py", 1, 1, label="beta")]
        rule = {"id": "demo.rule", "specificity": "narrowing"}

        def edge(to_id):
            return GraphEdge(
                from_id="alpha", to_id=to_id, relation=RelationKind.IMPLEMENTED_BY,
                confidence=Confidence.FRAMEWORK_INFERRED, metadata={"framework_rule": rule},
            )

        before = self.build(contents, nodes, [edge("beta")])
        after = self.build(contents, nodes, [edge("beta"), edge("alpha")])

        result = diff_agent_view(before, after)
        changed = {entry["id"]: entry["fields"] for entry in result["framework_links"]["changed"]}

        self.assertEqual(
            changed["alpha|demo.rule"]["to_node_ids"],
            {"before": ["beta"], "after": ["alpha", "beta"]},
        )


if __name__ == "__main__":
    unittest.main()
