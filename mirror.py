#!/usr/bin/env python3
"""
Gitea GitHub Mirror - Bulk mirror all GitHub repositories to a self-hosted Gitea instance.

This tool automatically discovers all repositories under your GitHub account
(including private, public, forked, organization-member, and collaborator repos)
and dispatches pull-mirror creation requests to your Gitea server using a
fire-and-forget pattern to avoid Nginx 504 timeout issues.

Usage:
    python3 mirror.py [--lang en|cn] [--yes] [--include-orgs] [--dry-run] [--timeout SECONDS]

Environment Variables (or .env file):
    GITEA_URL           - Your Gitea instance URL (e.g. https://git.example.com)
    GITEA_TOKEN         - Gitea API access token
    GITEA_USER          - Gitea username (repo owner)
    GITHUB_TOKEN        - GitHub personal access token (with 'repo' scope)
    GITHUB_USER         - GitHub username for filtering owner repos
    MIRROR_INTERVAL     - (Optional) Mirror sync interval (e.g. '8h0m0s', default: Gitea server default)
    REQUEST_TIMEOUT     - (Optional) HTTP request timeout in seconds (default: 15)
    MAX_RETRIES         - (Optional) Max retry attempts per repo (default: 3)
    RETRY_DELAY         - (Optional) Initial retry delay in seconds (default: 5)
    DISPATCH_DELAY      - (Optional) Delay between dispatches in seconds (default: 0.5)
    LOG_LEVEL           - (Optional) Logging level: DEBUG, INFO, WARNING, ERROR (default: INFO)
    REPORT_MAX_COUNT    - (Optional) Max number of archived reports to keep (default: 50)
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
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VERSION = "1.1.0"
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
║       Gitea ⇄ GitHub  Bulk Mirror Tool  v{VERSION}        ║
║       Mirror all your GitHub repos to Gitea             ║
╚══════════════════════════════════════════════════════════╝""",
        "prompt_github_token": "👉 Paste your GitHub Token (input is hidden, press Enter to confirm): ",
        "fetching": "\n🔍 Fetching your GitHub repository list via API...",
        "fetch_fail": "\n❌ Failed to fetch GitHub repos. Please check your token. Error: {}",
        "scan_result": "\n📦 Scanned {} repos total (Owned: {}, Org/Collab: {}).",
        "section_owned": "【Your Repositories】",
        "section_other": "\n【Organization & Collaborator Repositories】({} repos, owned by other accounts)",
        "vis_private": "🔒Private",
        "vis_public": "🌐Public ",
        "ask_include_orgs": "\n👉 Optional: Also mirror the {} org/collab repos listed above? (y/N, default N = only your own): ",
        "include_orgs_yes": "-> Including ALL {} repos.",
        "include_orgs_no": "-> Excluding org repos. Mirroring only your {} owned repos.",
        "confirm": "\n⚠️  FINAL CONFIRMATION: About to dispatch {} pull-mirror request(s) to Gitea. Proceed? (y/N): ",
        "cancelled": "Operation cancelled. You can re-run anytime.",
        "starting": "\n🚀 Starting bulk mirror dispatch (fire-and-forget mode)...",
        "dispatching": "🔄 [{}/{}] Dispatching -> {} ... ",
        "success": "✅ Created!",
        "dispatched": "📨 Dispatched! (server processing in background)",
        "already_exists": "⚠️  Already exists, skipped.",
        "retry": "   ⏳ Retry {}/{} in {}s ...",
        "failed": "❌ FAILED: {}",
        "done": "\n🎉 Bulk mirror dispatch complete!",
        "report_header": "Execution Report",
        "report_total": "Total repos processed",
        "report_success": "Confirmed created",
        "report_dispatched": "Dispatched (background)",
        "report_skipped": "Already existed (skipped)",
        "report_failed": "Failed",
        "report_duration": "Total duration",
        "report_avg": "Avg time per repo",
        "report_failed_list": "Failed Repositories",
        "report_saved": "📄 Report saved to: {}",
        "dry_run_prefix": "[DRY-RUN] ",
        "env_missing": "❌ Required environment variable '{}' is not set. Please configure your .env file or export it.",
    },
    "cn": {
        "banner": f"""
╔══════════════════════════════════════════════════════════╗
║       Gitea ⇄ GitHub  批量镜像同步工具  v{VERSION}       ║
║       将您的全部 GitHub 仓库镜像备份到 Gitea            ║
╚══════════════════════════════════════════════════════════╝""",
        "prompt_github_token": "👉 请粘贴您的 GitHub Token (输入不可见，按回车确认): ",
        "fetching": "\n🔍 正在通过 GitHub API 获取您的仓库列表...",
        "fetch_fail": "\n❌ 获取 GitHub 仓库失败，请检查 Token 是否正确且未过期。错误详情: {}",
        "scan_result": "\n📦 共扫描到 {} 个仓库 (个人所属: {} 个，组织/协作所属: {} 个)。",
        "section_owned": "【个人所属仓库】",
        "section_other": "\n【组织与协作仓库】(共 {} 个，属于其他账号或组织)",
        "vis_private": "🔒私有",
        "vis_public": "🌐公开",
        "ask_include_orgs": "\n👉 可选项：是否要将上述 {} 个【组织与协作仓库】一并同步？(y/N, 默认 N 仅同步个人库): ",
        "include_orgs_yes": "-> 已选择：合并同步全部 {} 个仓库。",
        "include_orgs_no": "-> 已选择：排除组织库，仅同步个人所属的 {} 个仓库。",
        "confirm": "\n⚠️  最终确认：即将向 Gitea 下发 {} 个仓库的【自动拉取镜像】创建请求。(输入 y 开始, 输入 n 退出): ",
        "cancelled": "已取消操作。您可以随时重新运行。",
        "starting": "\n🚀 开始批量下发镜像请求 (触发即走模式)...",
        "dispatching": "🔄 [{}/{}] 正在下发 -> {} ... ",
        "success": "✅ 已创建!",
        "dispatched": "📨 已下发! (服务器后台处理中)",
        "already_exists": "⚠️  已存在，跳过。",
        "retry": "   ⏳ 第 {}/{} 次重试，等待 {}s ...",
        "failed": "❌ 失败: {}",
        "done": "\n🎉 批量镜像请求下发完成！",
        "report_header": "执行报告",
        "report_total": "处理仓库总数",
        "report_success": "确认创建成功",
        "report_dispatched": "已下发(后台处理中)",
        "report_skipped": "已存在(跳过)",
        "report_failed": "失败",
        "report_duration": "总耗时",
        "report_avg": "平均每个仓库耗时",
        "report_failed_list": "失败仓库列表",
        "report_saved": "📄 报告已保存至: {}",
        "dry_run_prefix": "[演习模式] ",
        "env_missing": "❌ 必需的环境变量 '{}' 未设置。请配置 .env 文件或导出该变量。",
    },
}

# Global language reference (set in main)
T = MESSAGES["en"]


def load_env_file(filepath: Path) -> None:
    """Load environment variables from a .env file if it exists."""
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
    """Configure dual logging: console (colored) + rotating file."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOGS_DIR / f"mirror_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logger = logging.getLogger("gitea-mirror")
    logger.setLevel(getattr(logging, level_name.upper(), logging.INFO))

    # File handler - detailed
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(fh)

    # Console handler - concise
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(getattr(logging, level_name.upper(), logging.INFO))
    ch.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(ch)

    # Rotate old log files (keep last 30)
    _rotate_files(LOGS_DIR, "mirror_*.log", max_keep=30)

    logger.debug(f"Logging initialized. Log file: {log_file}")
    return logger


def _rotate_files(directory: Path, pattern: str, max_keep: int) -> None:
    """Delete oldest files matching pattern if count exceeds max_keep."""
    files = sorted(glob.glob(str(directory / pattern)))
    while len(files) > max_keep:
        oldest = files.pop(0)
        try:
            os.remove(oldest)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------
def fetch_github_repos(token: str, logger: logging.Logger) -> list:
    """Fetch all repos the authenticated user has access to."""
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
        logger.debug(f"Fetched page {page}, got {len(data)} repos (total: {len(repos)})")
        page += 1

    return repos


# ---------------------------------------------------------------------------
# Gitea Migration API — Fire-and-Forget Pattern
# ---------------------------------------------------------------------------
def dispatch_mirror_request(
    repo: dict,
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
) -> str:
    """
    Dispatch a pull-mirror creation request to Gitea for a single GitHub repo.

    Uses a fire-and-forget pattern with a short HTTP timeout to avoid
    Nginx 504 Gateway Timeout errors on large repositories. Gitea processes
    the actual git clone in a background goroutine queue, so we only need
    the API to acknowledge receipt of the request.

    Returns:
        'success'    — API returned 201 Created (confirmed)
        'dispatched' — Request was accepted but timed out waiting for response
                       (Gitea is processing in background, this is normal for large repos)
        'skipped'    — Repo already exists on Gitea (409 Conflict)
        'failed'     — Unrecoverable error after all retries
    """
    repo_name = repo["name"]
    clone_url = repo["clone_url"]
    is_private = repo["private"]

    if dry_run:
        logger.info(T["dry_run_prefix"] + f"Would dispatch: {clone_url} -> {gitea_url}/{gitea_user}/{repo_name}")
        return "success"

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
                # 201 Created — Gitea confirmed mirror was created
                return "success"

        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass

            # 409 Conflict or "already exists" → skip without retry
            if e.code == 409 or "already exists" in err_body.lower():
                return "skipped"

            # 504 Gateway Timeout — Nginx cut the connection, but Gitea
            # has already accepted the task and is cloning in background.
            # This is EXPECTED for large repos. Treat as dispatched.
            if e.code == 504:
                logger.debug(f"  [504 for {repo_name}] Nginx timeout, but Gitea is processing in background.")
                return "dispatched"

            # 502 Bad Gateway — similar to 504, Gitea is likely still processing
            if e.code == 502:
                logger.debug(f"  [502 for {repo_name}] Gateway error, Gitea may be processing in background.")
                return "dispatched"

            # 422 Unprocessable Entity — genuinely invalid request, no retry
            if e.code == 422:
                logger.error(T["failed"].format(f"HTTP {e.code}: {err_body[:200]}"))
                return "failed"

            # Other 5xx — retry with exponential backoff
            if attempt < max_retries:
                wait = retry_delay * (2 ** (attempt - 1))
                logger.warning(T["retry"].format(attempt, max_retries, wait))
                time.sleep(wait)
            else:
                logger.error(T["failed"].format(f"HTTP {e.code}: {err_body[:200]}"))
                return "failed"

        except (socket.timeout, urllib.error.URLError) as e:
            # Socket-level timeout or connection error.
            # For timeouts: Gitea likely accepted the request — treat as dispatched.
            err_str = str(e).lower()
            if "timed out" in err_str or "timeout" in err_str:
                logger.debug(f"  [Timeout for {repo_name}] Socket timeout, Gitea likely processing in background.")
                return "dispatched"

            # Connection refused / DNS error — retry
            if attempt < max_retries:
                wait = retry_delay * (2 ** (attempt - 1))
                logger.warning(T["retry"].format(attempt, max_retries, wait))
                time.sleep(wait)
            else:
                logger.error(T["failed"].format(str(e)[:200]))
                return "failed"

        except Exception as e:
            if attempt < max_retries:
                wait = retry_delay * (2 ** (attempt - 1))
                logger.warning(T["retry"].format(attempt, max_retries, wait))
                time.sleep(wait)
            else:
                logger.error(T["failed"].format(str(e)[:200]))
                return "failed"

    return "failed"


# ---------------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------------
def generate_report(
    results: dict,
    failed_repos: list,
    total_duration: float,
    total_count: int,
    lang: str,
    logger: logging.Logger,
) -> Path:
    """Generate a markdown execution report and archive it."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = REPORTS_DIR / f"report_{ts}.md"

    avg_time = total_duration / max(total_count, 1)
    mins, secs = divmod(int(total_duration), 60)
    hours, mins = divmod(mins, 60)
    duration_str = f"{hours}h {mins}m {secs}s" if hours else f"{mins}m {secs}s"

    t = MESSAGES[lang]

    lines = [
        f"# 📊 {t['report_header']}",
        f"",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"**Version:** v{VERSION}  ",
        f"**Mode:** Fire-and-Forget (async dispatch)  ",
        f"",
        f"## Summary",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| {t['report_total']} | {total_count} |",
        f"| {t['report_success']} | {results.get('success', 0)} |",
        f"| {t['report_dispatched']} | {results.get('dispatched', 0)} |",
        f"| {t['report_skipped']} | {results.get('skipped', 0)} |",
        f"| {t['report_failed']} | {results.get('failed', 0)} |",
        f"| {t['report_duration']} | {duration_str} |",
        f"| {t['report_avg']} | {avg_time:.1f}s |",
        f"",
    ]

    if failed_repos:
        lines.append(f"## ❌ {t['report_failed_list']}")
        lines.append("")
        for name, error in failed_repos:
            lines.append(f"- `{name}`: {error}")
        lines.append("")

    report_content = "\n".join(lines)
    report_file.write_text(report_content, encoding="utf-8")

    # Console summary
    logger.info("")
    logger.info("=" * 55)
    logger.info(f"📊 {t['report_header']}")
    logger.info(f"   {t['report_total']}:      {total_count}")
    logger.info(f"   {t['report_success']}:    {results.get('success', 0)}")
    logger.info(f"   {t['report_dispatched']}: {results.get('dispatched', 0)}")
    logger.info(f"   {t['report_skipped']}:    {results.get('skipped', 0)}")
    logger.info(f"   {t['report_failed']}:          {results.get('failed', 0)}")
    logger.info(f"   {t['report_duration']}:       {duration_str}")
    logger.info(f"   {t['report_avg']}:  {avg_time:.1f}s")
    logger.info("=" * 55)

    # Rotate old reports
    max_reports = int(os.environ.get("REPORT_MAX_COUNT", "50"))
    _rotate_files(REPORTS_DIR, "report_*.md", max_keep=max_reports)

    logger.info(t["report_saved"].format(report_file))
    return report_file


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    global T

    # Load .env file
    load_env_file(ENV_FILE)

    # Parse CLI arguments
    parser = argparse.ArgumentParser(
        description="Bulk mirror all GitHub repositories to a self-hosted Gitea instance.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--lang", choices=["en", "cn"], default=None, help="UI language (en/cn)")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip all confirmation prompts")
    parser.add_argument("--include-orgs", action="store_true", help="Include organization & collaborator repos")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without making any API calls to Gitea")
    parser.add_argument("--timeout", type=int, default=None, help="HTTP request timeout in seconds (default: 15)")
    args = parser.parse_args()

    # Normalize language: CLI > env > default
    lang = args.lang or os.environ.get("LANG_MIRROR", "en")
    if lang not in ("en", "cn"):
        lang = "en"
    T = MESSAGES[lang]

    # Setup logging
    log_level = os.environ.get("LOG_LEVEL", "INFO")
    logger = setup_logging(log_level)

    logger.info(T["banner"])

    # Validate required env vars
    gitea_url = os.environ.get("GITEA_URL", "").rstrip("/")
    gitea_token = os.environ.get("GITEA_TOKEN", "")
    gitea_user = os.environ.get("GITEA_USER", "")
    github_user = os.environ.get("GITHUB_USER", "")
    github_token = os.environ.get("GITHUB_TOKEN", "")

    for var_name, var_val in [("GITEA_URL", gitea_url), ("GITEA_TOKEN", gitea_token), ("GITEA_USER", gitea_user), ("GITHUB_USER", github_user)]:
        if not var_val:
            logger.error(T["env_missing"].format(var_name))
            sys.exit(1)

    # GitHub token: env var or interactive prompt
    if not github_token:
        import getpass
        github_token = getpass.getpass(T["prompt_github_token"])

    # Tuning parameters
    mirror_interval = os.environ.get("MIRROR_INTERVAL", "")
    request_timeout = args.timeout or int(os.environ.get("REQUEST_TIMEOUT", "15"))
    max_retries = int(os.environ.get("MAX_RETRIES", "3"))
    retry_delay = int(os.environ.get("RETRY_DELAY", "5"))
    dispatch_delay = float(os.environ.get("DISPATCH_DELAY", "0.5"))

    # ---- Phase 1: Fetch all GitHub repos ----
    logger.info(T["fetching"])
    all_repos = fetch_github_repos(github_token, logger)

    owner_repos = [r for r in all_repos if r["owner"]["login"].lower() == github_user.lower()]
    other_repos = [r for r in all_repos if r["owner"]["login"].lower() != github_user.lower()]

    logger.info(T["scan_result"].format(len(all_repos), len(owner_repos), len(other_repos)))

    # ---- Phase 2: Display categorized list ----
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

    # ---- Phase 3: Ask optional inclusion ----
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

    # ---- Phase 4: Final confirmation ----
    if not args.yes:
        confirm = input(T["confirm"].format(len(final_repos)))
        if confirm.strip().lower() != "y":
            logger.info(T["cancelled"])
            sys.exit(0)

    # ---- Phase 5: Fire-and-forget dispatch ----
    logger.info(T["starting"])
    start_time = time.time()
    results = {"success": 0, "dispatched": 0, "skipped": 0, "failed": 0}
    failed_repos = []

    for idx, repo in enumerate(final_repos, 1):
        logger.info(T["dispatching"].format(idx, len(final_repos), repo["name"]))

        status = dispatch_mirror_request(
            repo=repo,
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

        if status == "success":
            logger.info(T["success"])
        elif status == "dispatched":
            logger.info(T["dispatched"])
        elif status == "skipped":
            logger.info(T["already_exists"])
        else:
            failed_repos.append((repo["name"], "See log for details"))

        results[status] = results.get(status, 0) + 1

        # Short delay between dispatches to be kind to the API
        if not args.dry_run and idx < len(final_repos):
            time.sleep(dispatch_delay)

    total_duration = time.time() - start_time

    # ---- Phase 6: Generate report ----
    logger.info(T["done"])
    generate_report(results, failed_repos, total_duration, len(final_repos), lang, logger)


if __name__ == "__main__":
    main()
