# -*- coding: utf-8 -*-
"""文档检查 —— 这份仓库里全是字，所以「字对不对」就是全部的质量。

五个检查（每条都对应一种**不报错**的失效）：

  ① 相对链接可达（含**大小写**）
     文档改名/合并后别处的引用原地作废，读者点进去 404，维护者永远不知道。
     大小写不匹配在 Windows 上永远发现不了（文件系统不区分），但 CI 跑 Linux —— 会挂。

  ② README 必须有反馈入口
     一份没人知道怎么提意见的文档，等于一份只读文档。
     ★ 这正是本仓库本次补社区化改造要防的事：**没入口 = 提不了**。

  ③ CHANGELOG 降序 + 首条即当前版本
     没有这条，「最新版本是哪个」这个判断本身就不成立。

  ④ 能从 CHANGELOG 抽段（发版用 —— `--extract`）
     Release notes 派生自 CHANGELOG：单一真源，手写必然漂。

  ⑤ ★ 「迁移架构不得漏」
     本 SOP 自己踩过：0.1–0.2 描述了「谁该干什么」，
     却漏掉「**执行层会被不断重建**」这个必然事实 ——
     ⇒ 第一次重建就丢身份与在办事项，而且**不报错**。
     补了 0.3 之后，这条检查负责让它**不会再一次被删掉/漏掉**。

刻意排除的误判（假红比不报更坏）：
  · 代码块里的 `[x](y)` 不是链接
  · 外链 / 锚点 / mailto 不检查；只要目标存在即可（允许链到目录）

用法：
  python tools/docs_check.py                     # 查本仓库
  python tools/docs_check.py --selftest          # 自测（10 个用例 + 抽段）
  python tools/docs_check.py --extract 0.5.0 --out notes.md
退出码：0 = 通过
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from urllib.parse import unquote
except ImportError:  # pragma: no cover
    def unquote(s):
        return s

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LINK_RE = re.compile(r'!?\[[^\]]*\]\(([^)]*)\)')
RE_HEAD = re.compile(r'(?m)^##\s*\[([^\]]+)\]')
SKIP_DIRS = frozenset((".git", "__pycache__", "node_modules", ".venv", "venv",
                       "dist", "build", ".locks"))
EXTERNAL = ("http://", "https://", "mailto:", "tel:", "data:", "#", "/")


def iter_md(root):
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            if fn.lower().endswith((".md", ".markdown")):
                yield os.path.join(dp, fn)


def parse_target(raw):
    raw = raw.strip()
    if raw.startswith("<"):
        end = raw.find(">")
        raw = raw[1:end] if end != -1 else raw[1:]
    elif " " in raw:
        raw = raw.split()[0]
    return unquote(raw).split("#", 1)[0].strip()


def case_exact(path):
    parent, name = os.path.split(path)
    try:
        return name in os.listdir(parent or ".")
    except OSError:
        return None


def scan_links(root):
    out = []
    for md in sorted(iter_md(root)):
        base = os.path.dirname(md)
        rel = os.path.relpath(md, root)
        in_fence = False
        with open(md, encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f.read().splitlines(), 1):
                s = line.strip()
                if s.startswith("```") or s.startswith("~~~"):
                    in_fence = not in_fence
                    continue
                if in_fence:
                    continue
                for raw in LINK_RE.findall(line):
                    if not raw.strip():
                        continue
                    low = raw.strip().lower()
                    if low.startswith(EXTERNAL) or "://" in low:
                        continue
                    t = parse_target(raw)
                    if not t:
                        continue
                    full = os.path.normpath(os.path.join(base, t.replace("/", os.sep)))
                    if not os.path.exists(full):
                        out.append((rel, lineno, t, "目标不存在"))
                    elif case_exact(full) is False:
                        out.append((rel, lineno, t, "大小写不匹配（Linux CI 会 404）"))
    return out


def check_readme_entry(root):
    p = os.path.join(root, "README.md")
    if not os.path.isfile(p):
        return [("README.md", 0, "-", "README.md 不存在")]
    txt = open(p, encoding="utf-8", errors="replace").read()
    problems = []
    if "CONTRIBUTING.md" not in txt:
        problems.append(("README.md", 0, "CONTRIBUTING.md", "缺少贡献入口（新人不知道该怎么提意见）"))
    if "issues" not in txt.lower() and "discussions" not in txt.lower():
        problems.append(("README.md", 0, "issues/discussions",
                         "缺少反馈入口（没人知道该去哪说）"))
    return problems


def changelog_versions(root):
    p = os.path.join(root, "CHANGELOG.md")
    if not os.path.isfile(p):
        return []
    return RE_HEAD.findall(open(p, encoding="utf-8", errors="replace").read())


# ★ 「迁移架构不得漏」的判据词。
#   为什么是这几个而不是「有没有 §六 这个编号」：
#   编号会随重排而变，**规矩不会**。检查「判据在不在」，比检查「编到第几节」稳。
MIGRATION_MARKERS = (
    "迁移架构",            # 有这一整块
    "四律",                # 定了规矩，不是随口一提
    "会变的，不写死",       # 律一
    "权威，只有一处",       # 律二
    "入口，挂启动必读位",   # 律三
    "形状与接线",          # 律四
)


def check_migration_section(root):
    p = os.path.join(root, "README.md")
    if not os.path.isfile(p):
        return [("README.md", 0, "-", "README.md 不存在")]
    txt = open(p, encoding="utf-8", errors="replace").read()
    missing = [m for m in MIGRATION_MARKERS if m not in txt]
    if missing:
        return [("README.md", 0, " / ".join(missing),
                 "迁移架构这一节不完整或缺失（漏了它 = 描述了一个不存在的稳态）")]
    return []


def key(v):
    parts = [int(t) if t.isdigit() else -1 for t in v.split(".")]
    return tuple(parts + [0] * (4 - len(parts)))


def check_changelog(root):
    vs = changelog_versions(root)
    if not vs:
        return [("CHANGELOG.md", 0, "-", "没有可识别的版本条目（`## [x.y.z]`）")]
    problems = []
    ks = [key(v) for v in vs]
    for i in range(len(ks) - 1):
        if ks[i] < ks[i + 1]:
            problems.append(("CHANGELOG.md", 0, "%s < %s" % (vs[i], vs[i + 1]),
                             "条目不是降序（新的要在最上面）"))
    return problems


def extract(root, version):
    p = os.path.join(root, "CHANGELOG.md")
    text = open(p, encoding="utf-8", errors="replace").read()
    ms = list(RE_HEAD.finditer(text))
    for i, m in enumerate(ms):
        if m.group(1).strip() == version:
            end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
            body = re.sub(r'\n-{3,}\s*$', '', text[m.start():end].rstrip())
            return body
    return None


def check(root=ROOT, quiet=False, expect=None):
    if not quiet:
        print("=" * 70)
        print("文档检查（链接 / 反馈入口 / 变更日志 / 迁移架构）")
        print("=" * 70)

    links = scan_links(root)
    entry = check_readme_entry(root)
    clog = check_changelog(root)
    migr = check_migration_section(root)
    vs = changelog_versions(root)

    if not quiet:
        print("  扫描 markdown：%d 篇" % sum(1 for _ in iter_md(root)))
        print("  %s 相对链接可达        %s"
              % ("✅" if not links else "❌",
                 "全部可达" if not links else "%d 处失效" % len(links)))
        print("  %s README 有反馈入口    %s"
              % ("✅" if not entry else "❌",
                 "有" if not entry else "缺 %d 项" % len(entry)))
        print("  %s CHANGELOG 降序      %s"
              % ("✅" if not clog else "❌",
                 "最新 %s（共 %d 条）" % (vs[0] if vs else "?", len(vs))))
        print("  %s 迁移架构不得漏       %s"
              % ("✅" if not migr else "❌",
                 "四律齐全" if not migr else "缺判据词"))

    problems = links + entry + clog + migr
    if expect and (not vs or vs[0] != expect):
        problems.append(("CHANGELOG.md", 0, expect,
                         "当前版本（首条）%s ≠ 期望 %s" % (vs[0] if vs else "无", expect)))

    if problems:
        if not quiet:
            print("-" * 70)
        print("❌ 文档检查失败 %d 项：" % len(problems))
        for rel, lineno, t, why in problems:
            where = "%s:%d" % (rel.replace(os.sep, "/"), lineno) if lineno else rel
            print("   · %s  ->  %s   [%s]" % (where, t, why))
    elif not quiet:
        print("-" * 70)
        print("✅ 通过")
    if not quiet:
        print("=" * 70)
    return 1 if problems else 0


def _selftest():
    """★ 每个用例先清空目录再铺料 —— 用例之间不得互留状态（否则自测本身在骗人）。"""
    tmp = os.path.join(tempfile.gettempdir(), "sop-docs-check")
    fails = []

    # ★ 干净的 README 必须**自带**迁移架构块 —— 否则新的第 ⑤ 项会把所有正例判红
    MIGRATION_BLOCK = (
        "\n## 六、迁移架构（协作架构缺了它 = 残缺）\n\n"
        "### 6.6 迁移四律\n\n"
        "| # | 律 |\n|---|---|\n"
        "| 一 | 会变的，不写死 |\n"
        "| 二 | 权威，只有一处 |\n"
        "| 三 | 入口，挂启动必读位 |\n"
        "| 四 | 形状与接线，必须分离 |\n"
    )
    CLEAN_README = ("# x\n\n见 [a](docs/a.md)\n贡献见 [CONTRIBUTING.md](CONTRIBUTING.md)\n"
                    "问题提 issues\n" + MIGRATION_BLOCK)

    def write(rel, text):
        p = os.path.join(tmp, rel)
        d = os.path.dirname(p)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)

    def run(extra=None):
        return subprocess.run([sys.executable, "-X", "utf8", os.path.abspath(__file__),
                               "--root", tmp, "--quiet"] + (extra or []),
                              capture_output=True).returncode

    def base():
        write("README.md", CLEAN_README)
        write("CONTRIBUTING.md", "# 贡献\n")     # ★ README 链它，fixture 里就必须有它
        write("docs/a.md", "# a\n")
        write("CHANGELOG.md", "## [0.4.0] - a\n\n- 甲\n\n---\n\n## [0.3.0] - b\n\n- 乙\n")

    cases = [
        ("干净", base, None, 0),
        ("失效链接",
         lambda: (base(), write("README.md", CLEAN_README + "见 [旧](docs/gone.md)\n")), None, 1),
        ("代码块里的链接被忽略",
         lambda: (base(), write("README.md", CLEAN_README + "```\n[x](不存在.md)\n```\n")), None, 0),
        ("大小写不匹配",
         lambda: (base(), write("README.md", CLEAN_README + "见 [A](docs/A.md)\n")), None, 1),
        ("缺贡献入口",
         lambda: (base(), write("README.md", "# x\n见 [a](docs/a.md)\n")), None, 1),
        ("CHANGELOG 乱序",
         lambda: (base(), write("CHANGELOG.md", "## [0.3.0] - a\n\n## [0.4.0] - b\n")), None, 1),
        # ★ 第 ⑤ 项的两个反向用例 —— 证明「迁移架构不得漏」真的抓得到
        ("迁移架构整块被删",
         lambda: (base(), write("README.md", CLEAN_README.replace(MIGRATION_BLOCK, ""))), None, 1),
        ("四律只剩三条",
         lambda: (base(), write("README.md", CLEAN_README.replace("会变的，不写死", "甲"))), None, 1),
        ("--expect 不符 -> 拒发", base, ["--expect", "9.9.9"], 1),
        ("--expect 命中", base, ["--expect", "0.4.0"], 0),
    ]

    print("docs_check 自测")
    for name, setup, extra, want in cases:
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        setup()
        got = run(extra)
        ok = got == want
        print("  %s %-26s 期望退出码 %d，实际 %d" % ("✅" if ok else "❌", name, want, got))
        if not ok:
            fails.append(name)

    # 抽段：本版本内容要有，下一版本内容不能有
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    base()
    got = extract(tmp, "0.4.0")
    ok = got is not None and "甲" in got and "乙" not in got
    print("  %s %-26s %s" % ("✅" if ok else "❌", "抽段不越界", "不应含下一版本内容"))
    if not ok:
        fails.append("抽段")

    shutil.rmtree(tmp, ignore_errors=True)
    print("结果：%s" % ("✅ 全过" if not fails else "❌ 失败 %s" % fails))
    return 1 if fails else 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        return _selftest()
    root = argv[argv.index("--root") + 1] if "--root" in argv else ROOT
    if "--extract" in argv:
        v = argv[argv.index("--extract") + 1]
        body = extract(root, v)
        if body is None:
            print("❌ CHANGELOG.md 里没有 [%s]，可用：%s"
                  % (v, ", ".join(changelog_versions(root))), file=sys.stderr)
            return 1
        if "--out" in argv:
            out = argv[argv.index("--out") + 1]
            with open(out, "w", encoding="utf-8") as f:
                f.write(body + "\n")
            print("已写出 %s（%d 字）" % (out, len(body)))
        else:
            print(body)
        return 0
    expect = argv[argv.index("--expect") + 1] if "--expect" in argv else None
    return check(root, quiet="--quiet" in argv, expect=expect)


if __name__ == "__main__":
    sys.exit(main())
