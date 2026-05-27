#!/usr/bin/env python3
"""
Gitea GitHub Mirror - Bulk mirror all GitHub repositories to a self-hosted Gitea instance.

Uses concurrent workers to parallelize the synchronous Gitea migration API,
while strictly validating each response (HTTP 201 = confirmed success).

Usage:
    python3 mirror.py [--lang en|cn] [--yes] [--include-orgs] [--dry-run] [--workers N]

Environment Variables (or .env file):
    GITEA_URL           - Your Gitea instance URL (e.g. https://git.example.com)
    GITEA_TOKEN         - Gitea API access token
    GITEA_USER          - Gitea username (repo owner)
    GITHUB_TOKEN        - GitHub personal access token (with 'repo' scope)
    GITHUB_USER         - GitHub username for filtering owner repos
    MIRROR_INTERVAL     - (Optional) Mirror sync interval (e.g. '8h0m0s')
    REQUEST_TIMEOUT     - (Optional) HTTP timeout per request in seconds (default: 600)
    MAX_RETRIES         - (Optional) Max retry attempts per repo (default: 3)
    RETRY_DELAY         - (Optional) Initial retry delay in seconds (default: 10)
    MAX_WORKERS         - (Optional) Concurrent worker threads (default: 5)
    LOG_LEVEL           - (Optional) DEBUG, INFO, WARNING, ERROR (default: INFO)
    REPORT_MAX_COUNT    - (Optional) Max archived reports to keep (default: 50)
    LANG_MIRROR         - (Optional) Language: 'en' or 'cn' (default: en)

License: MIT
"""

import urllib.request
import urllib.error
import json
import time
import os
import sys
import logging
import argparse
import glob
import socket
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VERSION = "2.0.0"
SCRIPT_DIR = Path(__file__).resolve().parent
LOGS_DIR = SCRIPT_DIR / "logs"
REPORTS_DIR = SCRIPT_DIR / "reports"
ENV_FILE = SCRIPT_DIR / ".env"

# ---------------------------------------------------------------------------
# Internationalization (i18n)
# ---------------------------------------------------------------------------
MESSAGES = {
    "en": {
        "banner": f"""
╔══════════════════════════════════════════════════════════╗
║    Gitea ⇄ GitHub  Bulk Mirror Tool  v{VERSION}           ║
║    Concurrent • Strict • Reliable                       ║
╚══════════════════════════════════════════════════════════╝""",
        "prompt_github_token": "👉 Paste your GitHub Token (hidden input, press Enter): ",
        "fetching": "\n🔍 Fetching your GitHub repository list via API...",
        "fetch_fail": "\n❌ Failed to fetch GitHub repos. Check your token. Error: {}",
        "scan_result": "\n📦 Scanned {} repos total (Owned: {}, Org/Collab: {}).",
        "section_owned": "【Your Repositories】",
        "section_other": "\n【Organization & Collaborator Repositories】({} repos)",
        "vis_private": "🔒Private",
        "vis_public": "🌐Public ",
        "ask_include_orgs": "\n👉 Also mirror the {} org/collab repos? (y/N): ",
        "include_orgs_yes": "-> Including ALL {} repos.",
        "include_orgs_no": "-> Only your {} owned repos.",
        "confirm": "\n⚠️  CONFIRM: Create {} pull-mirror(s) on Gitea with {} workers? (y/N): ",
        "cancelled": "Cancelled.",
        "starting": "\n🚀 Starting concurrent migration ({} workers, {}s timeout per request)...",
        "mirroring": "[{}/{}] {} ... ",
        "success": "✅ Created ({:.1f}s)",
        "already_exists": "⏭️  Exists",
        "blocked": "🚫 Blocked (GitHub denied access)",
        "retry": "   ⏳ Retry {}/{} in {}s ({})",
        "failed": "❌ FAILED: {}",
        "done": "\n🎉 Migration complete!",
        "report_header": "Execution Report",
        "report_total": "Total repos",
        "report_success": "Successfully created",
        "report_skipped": "Already existed",
        "report_blocked": "Blocked by GitHub",
        "report_failed": "Failed",
        "report_duration": "Total duration",
        "report_avg": "Avg per repo",
        "report_workers": "Concurrent workers",
        "report_timeout": "Request timeout",
        "report_failed_list": "Failed Repositories",
        "report_blocked_list": "Blocked Repositories",
        "report_saved": "📄 Report: {}",
        "dry_run_prefix": "[DRY-RUN] ",
        "env_missing": "❌ Required env var '{}' not set. Configure .env or export it.",
    },
    "cn": {
        "banner": f"""
╔══════════════════════════════════════════════════════════╗
║    Gitea ⇄ GitHub  批量镜像同步工具  v{VERSION}           ║
║    并发执行 • 严格校验 • 结果可靠                       ║
╚══════════════════════════════════════════════════════════╝""",
        "prompt_github_token": "👉 请粘贴 GitHub Token (输入不可见，按回车确认): ",
        "fetching": "\n🔍 正在获取 GitHub 仓库列表...",
        "fetch_fail": "\n❌ 获取 GitHub 仓库失败，请检查 Token。错误: {}",
        "scan_result": "\n📦 共扫描到 {} 个仓库 (个人: {} 个，组织/协作: {} 个)。",
        "section_owned": "【个人所属仓库】",
        "section_other": "\n【组织与协作仓库】(共 {} 个)",
        "vis_private": "🔒私有",
        "vis_public": "🌐公开",
        "ask_include_orgs": "\n👉 是否一并同步上述 {} 个组织/协作仓库？(y/N): ",
        "include_orgs_yes": "-> 合并同步全部 {} 个仓库。",
        "include_orgs_no": "-> 仅同步个人所属的 {} 个仓库。",
        "confirm": "\n⚠️  最终确认: 即将以 {} 个并发线程创建 {} 个拉取镜像。(y/N): ",
        "cancelled": "已取消。",
        "starting": "\n🚀 开始并发迁移 ({} 个线程, 每请求 {}s 超时)...",
        "mirroring": "[{}/{}] {} ... ",
        "success": "✅ 已创建 ({:.1f}s)",
        "already_exists": "⏭️  已存在",
        "blocked": "🚫 已封锁 (GitHub 拒绝访问)",
        "retry": "   ⏳ 第 {}/{} 次重试, 等待 {}s ({})",
        "failed": "❌ 失败: {}",
        "done": "\n🎉 迁移完成!",
        "report_header": "执行报告",
        "report_total": "仓库总数",
        "report_success": "成功创建",
        "report_skipped": "已存在(跳过)",
        "report_blocked": "被 GitHub 封锁",
        "report_failed": "失败",
        "report_duration": "总耗时",
        "report_avg": "平均每仓库",
        "report_workers": "并发线程数",
        "report_timeout": "请求超时",
        "report_failed_list": "失败仓库列表",
        "report_blocked_list": "被封锁仓库列表",
        "report_saved": "📄 报告: {}",
        "dry_run_prefix": "[演习] ",
        "env_missing": "❌ 必需的环境变量 '{}' 未设置。请配置 .env 文件。",
    },
}

T = MESSAGES["en"]

# Thread-safe print lock
_print_lock = threading.Lock()


def load_env_file(filepath: Path) -> None:
    """Load .env file into os.environ (does not override existing vars)."""
    if not filepath.is_file():
        return
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("\"'")
                if key and key not in os.environ:
                    os.environ[key] = value


def setup_logging(level_name: str) -> logging.Logger:
    """Configure dual logging: console + file."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOGS_DIR / f"mirror_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logger = logging.getLogger("gitea-mirror")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(threadName)-12s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(getattr(logging, level_name.upper(), logging.INFO))
    ch.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(ch)

    _rotate_files(LOGS_DIR, "mirror_*.log", max_keep=30)
    return logger


def _rotate_files(directory: Path, pattern: str, max_keep: int) -> None:
    """Delete oldest files if count exceeds max_keep."""
    files = sorted(glob.glob(str(directory / pattern)))
    while len(files) > max_keep:
        try:
            os.remove(files.pop(0))
        except OSError:
            pass


# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------
def fetch_github_repos(token: str, logger: logging.Logger) -> list:
    """Fetch all repos the authenticated user has access to (paginated)."""
    repos = []
    page = 1
    while True:
        url = (
            f"https://api.github.com/user/repos"
            f"?affiliation=owner,collaborator,organization_member"
            f"&per_page=100&page={page}"
        )
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"token {token}")
        req.add_header("Accept", "application/vnd.github.v3+json")
        req.add_header("User-Agent", f"gitea-github-mirror/{VERSION}")

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.error(T["fetch_fail"].format(e))
            sys.exit(1)

        if not data:
            break
        repos.extend(data)
        logger.debug(f"GitHub API page {page}: {len(data)} repos (total: {len(repos)})")
        page += 1

    return repos


# ---------------------------------------------------------------------------
# Gitea Migration — Strict Synchronous with Retries
# ---------------------------------------------------------------------------
def migrate_single_repo(
    repo: dict,
    index: int,
    total: int,
    gitea_url: str,
    gitea_token: str,
    gitea_user: str,
    github_token: str,
    mirror_interval: str,
    request_timeout: int,
    max_retries: int,
    retry_delay: int,
    dry_run: bool,
    logger: logging.Logger,
) -> dict:
    """
    Migrate a single GitHub repo to Gitea. Blocks until Gitea returns 201 or fails.

    Returns a result dict: {name, status, duration, error}
    - status: 'success' | 'skipped' | 'blocked' | 'failed'
    """
    repo_name = repo["name"]
    clone_url = repo["clone_url"]
    is_private = repo["private"]
    start = time.time()

    with _print_lock:
        logger.info(T["mirroring"].format(index, total, repo_name))

    if dry_run:
        with _print_lock:
            logger.info(T["dry_run_prefix"] + f"{clone_url} -> {gitea_user}/{repo_name}")
        return {"name": repo_name, "status": "success", "duration": 0, "error": ""}

    payload = {
        "auth_token": github_token,
        "clone_addr": clone_url,
        "mirror": True,
        "repo_name": repo_name,
        "repo_owner": gitea_user,
        "private": is_private,
        "service": "github",
        "wiki": False,
        "labels": False,
        "issues": False,
        "pull_requests": False,
        "releases": False,
        "milestones": False,
    }
    if mirror_interval:
        payload["mirror_interval"] = mirror_interval

    last_error = ""

    for attempt in range(1, max_retries + 1):
        req = urllib.request.Request(
            f"{gitea_url}/api/v1/repos/migrate",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
        )
        req.add_header("Authorization", f"token {gitea_token}")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", f"gitea-github-mirror/{VERSION}")

        try:
            with urllib.request.urlopen(req, timeout=request_timeout) as resp:
                resp.read()
                elapsed = time.time() - start
                with _print_lock:
                    logger.info(T["success"].format(elapsed))
                return {"name": repo_name, "status": "success", "duration": elapsed, "error": ""}

        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass

            # --- 409: Already exists → skip (no retry) ---
            if e.code == 409 or "already exists" in err_body.lower():
                with _print_lock:
                    logger.info(T["already_exists"])
                return {"name": repo_name, "status": "skipped", "duration": time.time() - start, "error": ""}

            # --- 403: GitHub blocked the repo (DMCA, TOS, etc.) → skip (no retry) ---
            if e.code == 403 or ("403" in err_body and "access blocked" in err_body.lower()):
                reason = _extract_error_message(err_body)
                with _print_lock:
                    logger.warning(T["blocked"] + f" — {reason}")
                return {"name": repo_name, "status": "blocked", "duration": time.time() - start, "error": reason}

            # --- 422: Invalid request → fail (no retry) ---
            if e.code == 422:
                reason = _extract_error_message(err_body)
                last_error = f"HTTP 422: {reason}"
                with _print_lock:
                    logger.error(T["failed"].format(last_error))
                return {"name": repo_name, "status": "failed", "duration": time.time() - start, "error": last_error}

            # --- 5xx / other: Retry with exponential backoff ---
            last_error = f"HTTP {e.code}: {_extract_error_message(err_body)}"
            if attempt < max_retries:
                wait = retry_delay * (2 ** (attempt - 1))
                with _print_lock:
                    logger.warning(T["retry"].format(attempt, max_retries, wait, last_error))
                time.sleep(wait)
            else:
                with _print_lock:
                    logger.error(T["failed"].format(last_error))

        except (socket.timeout, urllib.error.URLError) as e:
            last_error = f"Network: {str(e)[:150]}"
            if attempt < max_retries:
                wait = retry_delay * (2 ** (attempt - 1))
                with _print_lock:
                    logger.warning(T["retry"].format(attempt, max_retries, wait, last_error))
                time.sleep(wait)
            else:
                with _print_lock:
                    logger.error(T["failed"].format(last_error))

        except Exception as e:
            last_error = f"Unexpected: {str(e)[:150]}"
            if attempt < max_retries:
                wait = retry_delay * (2 ** (attempt - 1))
                with _print_lock:
                    logger.warning(T["retry"].format(attempt, max_retries, wait, last_error))
                time.sleep(wait)
            else:
                with _print_lock:
                    logger.error(T["failed"].format(last_error))

    return {"name": repo_name, "status": "failed", "duration": time.time() - start, "error": last_error}


def _extract_error_message(body: str) -> str:
    """Try to extract a clean error message from Gitea/GitHub JSON or HTML response."""
    body = body.strip()
    # Try JSON
    try:
        data = json.loads(body)
        return data.get("message", body[:200])
    except (json.JSONDecodeError, AttributeError):
        pass
    # Strip HTML tags for Nginx error pages
    if "<html" in body.lower():
        import re
        text = re.sub(r"<[^>]+>", " ", body)
        text = " ".join(text.split())
        return text[:200]
    return body[:200]


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def generate_report(
    all_results: list,
    total_duration: float,
    max_workers: int,
    request_timeout: int,
    lang: str,
    logger: logging.Logger,
) -> Path:
    """Generate a Markdown execution report."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = REPORTS_DIR / f"report_{ts}.md"

    counts = {"success": 0, "skipped": 0, "blocked": 0, "failed": 0}
    failed_list = []
    blocked_list = []
    for r in all_results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        if r["status"] == "failed":
            failed_list.append((r["name"], r["error"]))
        elif r["status"] == "blocked":
            blocked_list.append((r["name"], r["error"]))

    total_count = len(all_results)
    avg_time = total_duration / max(total_count, 1)
    mins, secs = divmod(int(total_duration), 60)
    hours, mins = divmod(mins, 60)
    dur_str = f"{hours}h {mins}m {secs}s" if hours else f"{mins}m {secs}s"

    t = MESSAGES[lang]

    lines = [
        f"# 📊 {t['report_header']}",
        "",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"**Version:** v{VERSION}  ",
        f"**Mode:** Concurrent (strict synchronous per worker)  ",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| {t['report_total']} | {total_count} |",
        f"| {t['report_success']} | {counts['success']} |",
        f"| {t['report_skipped']} | {counts['skipped']} |",
        f"| {t['report_blocked']} | {counts['blocked']} |",
        f"| {t['report_failed']} | {counts['failed']} |",
        f"| {t['report_workers']} | {max_workers} |",
        f"| {t['report_timeout']} | {request_timeout}s |",
        f"| {t['report_duration']} | {dur_str} |",
        f"| {t['report_avg']} | {avg_time:.1f}s |",
        "",
    ]

    if blocked_list:
        lines += [f"## 🚫 {t['report_blocked_list']}", ""]
        for name, err in blocked_list:
            lines.append(f"- `{name}`: {err}")
        lines.append("")

    if failed_list:
        lines += [f"## ❌ {t['report_failed_list']}", ""]
        for name, err in failed_list:
            lines.append(f"- `{name}`: {err}")
        lines.append("")

    report_file.write_text("\n".join(lines), encoding="utf-8")

    # Console summary
    logger.info("")
    logger.info("=" * 55)
    logger.info(f"📊 {t['report_header']}")
    logger.info(f"   {t['report_total']}:       {total_count}")
    logger.info(f"   {t['report_success']}:   {counts['success']}")
    logger.info(f"   {t['report_skipped']}:   {counts['skipped']}")
    logger.info(f"   {t['report_blocked']}:  {counts['blocked']}")
    logger.info(f"   {t['report_failed']}:         {counts['failed']}")
    logger.info(f"   {t['report_workers']}:   {max_workers}")
    logger.info(f"   {t['report_timeout']}:    {request_timeout}s")
    logger.info(f"   {t['report_duration']}:      {dur_str}")
    logger.info(f"   {t['report_avg']}:    {avg_time:.1f}s")
    logger.info("=" * 55)

    max_reports = int(os.environ.get("REPORT_MAX_COUNT", "50"))
    _rotate_files(REPORTS_DIR, "report_*.md", max_keep=max_reports)
    logger.info(t["report_saved"].format(report_file))
    return report_file


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    global T

    load_env_file(ENV_FILE)

    parser = argparse.ArgumentParser(
        description="Bulk mirror all GitHub repos to Gitea (concurrent, strict).",
    )
    parser.add_argument("--lang", choices=["en", "cn"], default=None)
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmations")
    parser.add_argument("--include-orgs", action="store_true", help="Include org/collab repos")
    parser.add_argument("--dry-run", action="store_true", help="Simulate only")
    parser.add_argument("--workers", type=int, default=None, help="Concurrent workers (default: 5)")
    parser.add_argument("--timeout", type=int, default=None, help="Request timeout seconds (default: 600)")
    args = parser.parse_args()

    lang = args.lang or os.environ.get("LANG_MIRROR", "en")
    if lang not in ("en", "cn"):
        lang = "en"
    T = MESSAGES[lang]

    log_level = os.environ.get("LOG_LEVEL", "INFO")
    logger = setup_logging(log_level)
    logger.info(T["banner"])

    # Required env vars
    gitea_url = os.environ.get("GITEA_URL", "").rstrip("/")
    gitea_token = os.environ.get("GITEA_TOKEN", "")
    gitea_user = os.environ.get("GITEA_USER", "")
    github_user = os.environ.get("GITHUB_USER", "")
    github_token = os.environ.get("GITHUB_TOKEN", "")

    for var, val in [("GITEA_URL", gitea_url), ("GITEA_TOKEN", gitea_token), ("GITEA_USER", gitea_user), ("GITHUB_USER", github_user)]:
        if not val:
            logger.error(T["env_missing"].format(var))
            sys.exit(1)

    if not github_token:
        import getpass
        github_token = getpass.getpass(T["prompt_github_token"])

    # Tuning
    mirror_interval = os.environ.get("MIRROR_INTERVAL", "")
    request_timeout = args.timeout or int(os.environ.get("REQUEST_TIMEOUT", "600"))
    max_retries = int(os.environ.get("MAX_RETRIES", "3"))
    retry_delay = int(os.environ.get("RETRY_DELAY", "10"))
    max_workers = args.workers or int(os.environ.get("MAX_WORKERS", "5"))

    # Phase 1: Fetch
    logger.info(T["fetching"])
    all_repos = fetch_github_repos(github_token, logger)

    owner_repos = [r for r in all_repos if r["owner"]["login"].lower() == github_user.lower()]
    other_repos = [r for r in all_repos if r["owner"]["login"].lower() != github_user.lower()]

    logger.info(T["scan_result"].format(len(all_repos), len(owner_repos), len(other_repos)))

    # Phase 2: List
    logger.info("-" * 55)
    logger.info(T["section_owned"])
    for i, repo in enumerate(owner_repos, 1):
        vis = T["vis_private"] if repo["private"] else T["vis_public"]
        logger.info(f"  {i:03d}. [{vis}] {repo['name']}")

    if other_repos:
        logger.info(T["section_other"].format(len(other_repos)))
        for i, repo in enumerate(other_repos, 1):
            vis = T["vis_private"] if repo["private"] else T["vis_public"]
            logger.info(f"  {i:03d}. [{vis}] [{repo['owner']['login']}] {repo['name']}")
    logger.info("-" * 55)

    # Phase 3: Filter
    final_repos = list(owner_repos)
    if other_repos and not args.include_orgs:
        if args.yes:
            logger.info(T["include_orgs_no"].format(len(owner_repos)))
        else:
            choice = input(T["ask_include_orgs"].format(len(other_repos)))
            if choice.strip().lower() == "y":
                final_repos = list(all_repos)
                logger.info(T["include_orgs_yes"].format(len(final_repos)))
            else:
                logger.info(T["include_orgs_no"].format(len(final_repos)))
    elif args.include_orgs:
        final_repos = list(all_repos)
        logger.info(T["include_orgs_yes"].format(len(final_repos)))

    # Phase 4: Confirm
    if not args.yes:
        confirm = input(T["confirm"].format(len(final_repos), max_workers))
        if confirm.strip().lower() != "y":
            logger.info(T["cancelled"])
            sys.exit(0)

    # Phase 5: Concurrent migration
    logger.info(T["starting"].format(max_workers, request_timeout))
    start_time = time.time()
    all_results = []

    # Assign indices before submitting to thread pool
    indexed_repos = list(enumerate(final_repos, 1))

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="mirror") as pool:
        futures = {}
        for idx, repo in indexed_repos:
            future = pool.submit(
                migrate_single_repo,
                repo=repo,
                index=idx,
                total=len(final_repos),
                gitea_url=gitea_url,
                gitea_token=gitea_token,
                gitea_user=gitea_user,
                github_token=github_token,
                mirror_interval=mirror_interval,
                request_timeout=request_timeout,
                max_retries=max_retries,
                retry_delay=retry_delay,
                dry_run=args.dry_run,
                logger=logger,
            )
            futures[future] = repo["name"]

        for future in as_completed(futures):
            try:
                result = future.result()
                all_results.append(result)
            except Exception as e:
                name = futures[future]
                logger.error(f"❌ Unexpected thread error for {name}: {e}")
                all_results.append({"name": name, "status": "failed", "duration": 0, "error": str(e)})

    total_duration = time.time() - start_time

    # Phase 6: Report
    logger.info(T["done"])
    generate_report(all_results, total_duration, max_workers, request_timeout, lang, logger)


if __name__ == "__main__":
    main()
