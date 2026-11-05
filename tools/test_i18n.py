"""Run with: python3 -m unittest discover -s tools"""
import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import i18n  # noqa: E402
import jslex  # noqa: E402

REPO = i18n.ROOT


def strings(src):
    return [src[t.start:t.end] for t in jslex.tokenize(src) if t.kind == 'string']


class Lexer(unittest.TestCase):
    def test_quote_in_regex_does_not_pair_with_strings(self):
        src = 'const a = /^x \\("[^"]+"\\)$/.test(m ?? ""); el.child("Spaces");'
        self.assertEqual(strings(src), ['""', '"Spaces"'])

    def test_slash_in_character_class_does_not_end_regex(self):
        self.assertEqual(strings('p.split(/[/"]/); f("a");'), ['"a"'])

    def test_division_is_not_a_regex(self):
        self.assertEqual(strings('x = a / b; y("t"); z = (c) / 2; w("u");'), ['"t"', '"u"'])

    def test_quote_in_comments_is_ignored(self):
        self.assertEqual(strings('// it\'s "here\n/* don\'t */ f("a");'), ['"a"'])

    def test_template_nests_strings_and_templates(self):
        src = '`a ${x ? `b ${y}` : "c"} d`'
        (t,) = jslex.tokenize(src)
        self.assertEqual((t.kind, t.end), ('template', len(src)))
        self.assertEqual([c.kind for c in t.children], ['template', 'string'])

    def test_braces_in_template_holes(self):
        (t,) = jslex.tokenize('`${{ a: "}" }.a}`')
        self.assertEqual(len(t.holes), 1)

    def test_string_value(self):
        for literal, value in [(r'"a\u2026"', 'a…'), (r'"\u{1F600}"', '😀'), (r'"\ud83d\ude00"', '😀'),
                               (r'"\x41"', 'A'), (r'"it\'s"', "it's"), (r'"\n"', '\n'), (r"'\"'", '"')]:
            self.assertEqual(jslex.string_value(literal), value)

    def test_holes_allow_text_and_order_to_change(self):
        before = 'A ${x} ${y ? `to ${z}` : "none"}'
        after = '${y ? `至 ${z}` : "无"} 甲 ${x}'
        self.assertEqual(jslex.holes(before), jslex.holes(after))

    def test_holes_catch_changed_code(self):
        for after in ['A ${evil()} ${y ? `to ${z}` : "none"}',
                      'A ${x} ${y ? `to ${evil()}` : "none"}',
                      'A ${x} ${y ? `to ${z}` : "none" + evil()}']:
            self.assertNotEqual(jslex.holes('A ${x} ${y ? `to ${z}` : "none"}'), jslex.holes(after))

    def test_holes_reject_leaving_the_template(self):
        with self.assertRaises(jslex.LexError):
            jslex.holes('a` + evil() + `b')


CATALOG = {'locale': 'xx', 'name': 'X', 'title': 'Herdr X',
           'literals': {'Save': 'Sauver', 'Quote': 'say "hi"', 'Empty': ''},
           'templates': {'Hi ${name}': 'Salut ${name}'},
           'per_file': {'a/main.js': {'Save': None}}}


class Translate(unittest.TestCase):
    def run_it(self, src, file='b/main.js'):
        risky = []
        out, _ = i18n.translate(src, i18n.lookup(CATALOG, file), risky)
        return out, risky

    def test_literal_is_encoded_safely(self):
        self.assertEqual(self.run_it('f("Quote");')[0], 'f("say \\"hi\\"");')

    def test_escaped_source_text_matches(self):
        self.assertEqual(self.run_it(r'f("\u0053ave");')[0], 'f("Sauver");')

    def test_empty_translation_keeps_english(self):
        self.assertEqual(self.run_it('f("Empty");')[0], 'f("Empty");')

    def test_per_file_null_keeps_english(self):
        self.assertEqual(self.run_it('f("Save");', 'a/main.js')[0], 'f("Save");')

    def test_template_and_nested_text(self):
        self.assertEqual(self.run_it('f(`Hi ${name}`, `${x ? "Save" : y}`);')[0],
                         'f(`Salut ${name}`, `${x ? "Sauver" : y}`);')

    def test_only_the_import_of_herdr_moves(self):
        out = self.run_it('import { run } from "herdr"; f("herdr");')[0]
        self.assertEqual(out, 'import { run } from "./api.js"; f("herdr");')

    def test_compared_text_stays_and_is_reported(self):
        out, risky = self.run_it('if (a === "Save" || "Save" !== b) f(x ? "Save" : y); switch (c) { case "Save": }')
        self.assertEqual(out, 'if (a === "Save" || "Save" !== b) f(x ? "Sauver" : y); switch (c) { case "Save": }')
        self.assertEqual(risky, ['Save', 'Save', 'Save'])

    def test_only_text_changes(self):
        src = 'const a = /"/.test(b) ? "Save" : `Hi ${name}`; // "Save"\n'
        self.assertEqual(jslex.skeleton(src), jslex.skeleton(self.run_it(src)[0]))

    def test_problems(self):
        bad = {**CATALOG, 'templates': {'Hi ${name}': 'Salut ${evil()}'}}
        self.assertTrue(i18n.problems(bad))
        bad = {**CATALOG, 'templates': {'Hi ${name}': 'x` + evil() + `'}}
        self.assertTrue(i18n.problems(bad))
        self.assertEqual(i18n.problems(CATALOG), [])


class Keys(unittest.TestCase):
    CFG = {'mods': ['picker'], 'frames': ['settings'], 'keys': {'app.settings': 'settings'}}

    def test_keys(self):
        bindings = {'a': 'app.settings', 'b': 'mod.open:picker', 'c': 'tab.new', 'd': 'mod.open:other',
                    'e': 'app.settings:updates', 'f': {'command': 'app.settings'},
                    'g': {'command': 'app.settings', 'args': {'section': 'look'}},
                    'h': {'command': 'mod.open', 'args': {'name': 'picker'}}}
        self.assertEqual(i18n.keys_section(bindings, 'xx-', self.CFG), {
            'a': 'mod.open:xx-settings', 'b': 'mod.open:xx-picker',
            'f': 'mod.open:xx-settings', 'h': 'mod.open:xx-picker'})


class Repo(unittest.TestCase):
    """A whole repository with a tiny herdr-app, built and installed."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.saved = i18n.ROOT, i18n.LOCALES, i18n.SOURCE
        self.addCleanup(lambda: (setattr(i18n, 'ROOT', self.saved[0]), setattr(i18n, 'LOCALES', self.saved[1]),
                                 setattr(i18n, 'SOURCE', self.saved[2])))
        root = self.tmp / 'repo'
        (root / 'tools').mkdir(parents=True)
        (root / 'source').mkdir()
        (root / 'locales').mkdir()
        shutil.copy(REPO / 'tools' / 'shim.js', root / 'tools')
        shutil.copy(REPO / 'tools' / 'RECIPE.md', root / 'tools')
        i18n.ROOT, i18n.LOCALES, i18n.SOURCE = root, root / 'locales', root / 'source'
        i18n.write_json(root / 'upstream.json', {
            'repository': 'x/y', 'tag': 'v1', 'commit': 'abc', 'mods': ['menu'], 'frames': ['settings'],
            'screens': {'settings': {'kind': 'dialog'}}, 'keys': {'app.settings': 'settings'},
            'patches': [{'file': 'settings/main.js', 'find': 'const LOOKS = {',
                         'replace': 'const LOOKS = { "{layout}": {title},'}]})
        i18n.write_json(root / 'source' / 'rules.json', {'ignore': ['Skip me', 'Herdr'], 'include': [
            {'file': 'menu/main.js', 'text': 'open'}]})
        self.up = self.tmp / 'up'
        for rel, text in {
            'defaults/mods/menu/main.js': 'import { run } from "herdr";\nf("Save", "Skip me", `Hi ${name}`, "open");\n',
            'defaults/mods/menu/mod.json': '{ "place": "left", "title": "Save" }',
            'defaults/frame/settings/main.js': 'const LOOKS = { main: "Herdr" };\nf("New words here");\n',
            'defaults/frame/settings/mod.json': '{ "place": "none" }',
            'defaults/layouts/main.json': '{"id": "root", "children": [{"content": {"mod": "menu"}}, {"content": {"mod": "other"}}]}',
            'defaults/keys.json': '{"global": {"ctrl-,": "app.settings", "ctrl-t": "tab.new"}}',
            'defaults/keys.macos.json': '{"global": {"cmd-,": "app.settings"}}',
            'LICENSE': 'license',
        }.items():
            (self.up / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.up / rel).write_text(text)
        i18n.write_json(root / 'locales' / 'xx.json', CATALOG)
        self.args = argparse.Namespace(upstream=str(self.up), locales=[], verbose=False, strict=False)
        i18n.extract(self.args)
        i18n.build(self.args)
        self.out = root / 'xx'
        self.home = self.tmp / 'home'
        (self.home / 'layouts').mkdir(parents=True)
        (self.home / 'mods').mkdir()

    def install(self, keys=False):
        i18n.install(argparse.Namespace(locale='xx', home=str(self.home), keys=keys))

    def test_extract_lists_text_and_skips_rules(self):
        data = json.loads((i18n.SOURCE / 'strings.json').read_text())
        self.assertEqual(set(data['literals']), {'Save', 'New words here', 'open'})
        self.assertEqual(data['per_file'], {'menu/main.js': ['open']})
        self.assertEqual(set(data['templates']), {'Hi ${name}'})

    def test_built_mod(self):
        main = (self.out / 'mods' / 'xx-menu' / 'main.js').read_text()
        self.assertTrue(main.startswith(i18n.MARK))
        self.assertIn('from "./api.js"', main)
        self.assertIn('f("Sauver", "Skip me", `Salut ${name}`, "open")', main)
        self.assertEqual(json.loads((self.out / 'mods' / 'xx-menu' / 'mod.json').read_text()),
                         {'place': 'none', 'title': 'Sauver'})
        settings = (self.out / 'mods' / 'xx-settings' / 'main.js').read_text()
        self.assertIn('const LOOKS = { "xx": "Herdr X", main: "Herdr" }', settings)

    def test_built_layout_and_keys(self):
        tree = json.loads((self.out / 'layouts' / 'xx.json').read_text())
        self.assertEqual([c['content']['mod'] for c in tree['children']], ['xx-menu', 'other'])
        self.assertEqual(tree['terminal_menu'], 'xx-menu')
        self.assertEqual(json.loads((self.out / 'keys.json').read_text()),
                         {'layout:xx': {'ctrl-,': 'mod.open:xx-settings'}})

    def test_patch_that_stopped_matching_fails_the_build(self):
        (self.up / 'defaults/frame/settings/main.js').write_text('const OTHER = {};')
        with self.assertRaises(SystemExit):
            i18n.build(self.args)

    def test_check_reports_coverage(self):
        self.args.strict = True
        with self.assertRaises(SystemExit):
            i18n.check(self.args)  # "New words here" is missing
        catalog = json.loads((i18n.LOCALES / 'xx.json').read_text())
        catalog['literals']['New words here'] = 'Mots'
        catalog['per_file'] = {'menu/main.js': {'open': 'ouvert'}}
        del catalog['literals']['Quote'], catalog['literals']['Empty']
        i18n.write_json(i18n.LOCALES / 'xx.json', catalog)
        i18n.check(self.args)

    def test_new_locale_starts_empty_and_builds(self):
        i18n.new(argparse.Namespace(locale='fr', name='Français', title='Herdr Français'))
        catalog = json.loads((i18n.LOCALES / 'fr.json').read_text())
        self.assertEqual(catalog['literals']['Save'], '')
        self.assertNotIn('open', catalog['literals'])  # an id elsewhere: only ever per file
        self.assertEqual(catalog['per_file'], {'menu/main.js': {'open': ''}})
        self.args.locales = ['fr']
        i18n.build(self.args)
        # Untranslated stays English, even the per-file words.
        self.assertIn('f("Save", "Skip me", `Hi ${name}`, "open")', (i18n.ROOT / 'fr' / 'mods' / 'fr-menu' / 'main.js').read_text())

    def test_bad_locale_names_never_reach_rmtree(self):
        with self.assertRaises(SystemExit):
            i18n.catalogs(['tools'])
        with self.assertRaises(SystemExit):
            i18n.catalogs(['../x'])

    def test_install_and_reinstall(self):
        self.install()
        self.assertTrue((self.home / 'mods' / 'xx-menu' / 'main.js').exists())
        self.assertTrue((self.home / 'layouts' / 'xx.json').exists())
        (self.home / 'mods' / 'xx-old').mkdir()
        (self.home / 'mods' / 'xx-old' / 'main.js').write_text(f'{i18n.MARK} from herdr-app v0 x (xx).\n')
        self.install()
        self.assertFalse((self.home / 'mods' / 'xx-old').exists())
        self.assertEqual(sorted(p.name for p in (self.home / 'mods').iterdir()), ['xx-menu', 'xx-settings'])

    def test_install_leaves_other_mods_alone(self):
        for name, first in [('xx-mine', '// my own mod\n'), ('xx-yy-menu', f'{i18n.MARK} from herdr-app v1 x (xx-YY).\n')]:
            (self.home / 'mods' / name).mkdir()
            (self.home / 'mods' / name / 'main.js').write_text(first)
        self.install()
        self.assertTrue((self.home / 'mods' / 'xx-mine').exists())
        self.assertTrue((self.home / 'mods' / 'xx-yy-menu').exists())

    def test_install_refuses_to_replace_what_it_did_not_write(self):
        (self.home / 'mods' / 'xx-menu').mkdir()
        (self.home / 'mods' / 'xx-menu' / 'main.js').write_text('// my own mod\n')
        with self.assertRaises(SystemExit):
            self.install()
        self.assertEqual((self.home / 'mods' / 'xx-menu' / 'main.js').read_text(), '// my own mod\n')
        shutil.rmtree(self.home / 'mods' / 'xx-menu')
        (self.home / 'layouts' / 'xx.json').write_text('{"terminal_menu": "mine"}')
        with self.assertRaises(SystemExit):
            self.install()

    def test_install_keys_follow_the_persons_own_bindings(self):
        i18n.write_json(self.home / 'keys.json', {'global': {'alt-s': 'app.settings', 'ctrl-t': 'tab.new'}})
        self.install(keys=True)
        keys = json.loads((self.home / 'keys.json').read_text())
        self.assertEqual(keys['layout:xx'], {'alt-s': 'mod.open:xx-settings'})
        self.assertEqual(keys['global']['ctrl-t'], 'tab.new')


class Shipped(unittest.TestCase):
    """The committed builds, against the pinned herdr-app when it's in .cache/."""

    def test_builds_change_only_text(self):
        cfg = i18n.config()
        up = REPO / '.cache' / f"herdr-app-{cfg['tag']}"
        if not up.exists():
            self.skipTest('run i18n.py fetch first')
        for code, catalog in i18n.catalogs([]):
            layout = code.lower()
            for name, folder, scripts in i18n.sources(up):
                for script in scripts:
                    built = (REPO / layout / 'mods' / f'{layout}-{name}' / script.name).read_text()
                    self.assertTrue(built.startswith(i18n.MARK))
                    original = i18n.apply_patches(script.read_text(), f'{name}/{script.name}', cfg, layout, catalog['title'])
                    self.assertEqual(jslex.skeleton(built), jslex.skeleton(original), f'{code} {name}/{script.name}')


if __name__ == '__main__':
    unittest.main()
