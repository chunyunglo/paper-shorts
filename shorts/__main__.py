"""CLI: python -m shorts <command>

  make              pick a paper and build out/<episode>/video.mp4 (no uploads)
  publish DIR       upload an episode folder to YouTube, Instagram, Threads; record history
  comments          triage and answer new comments on recent episodes
  refresh-tokens    renew Instagram/Threads long-lived tokens and store them as repo secrets
  review-*          owner review issue: open / list approved / close / skip unapproved
  voices            render one sentence in several voices for choosing (out/voices/)
  keepalive         re-enable scheduled workflows so GitHub never auto-disables them
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .safelog import install_excepthook


def main() -> None:
    ap = argparse.ArgumentParser(prog="shorts")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make")
    m.add_argument("--script-json", type=Path)
    m.add_argument("--paper-json", type=Path)
    m.add_argument("--preview-every", type=int, default=0)
    pb = sub.add_parser("publish")
    pb.add_argument("episode_dir", type=Path)
    pb.add_argument("--video-base-url", required=True,
                    help="Public URL prefix of the release assets video_zh.mp4 / video_en.mp4")
    pb.add_argument("--only", nargs="*", choices=["youtube", "instagram", "threads"])
    c = sub.add_parser("comments")
    c.add_argument("--dry-run", action="store_true", help="classify only; post, hide, and email nothing")
    sub.add_parser("refresh-tokens")
    sub.add_parser("keepalive")
    sub.add_parser("voices")
    ro = sub.add_parser("review-open")
    ro.add_argument("episode_dir", type=Path)
    ro.add_argument("tag")
    sub.add_parser("review-approved")
    rc = sub.add_parser("review-close")
    rc.add_argument("number", type=int)
    rc.add_argument("--message", required=True)
    rc.add_argument("--published", action="store_true")
    sub.add_parser("review-skip-unapproved")
    args = ap.parse_args()

    if args.cmd == "make":
        install_excepthook(strict=False)
        from .pipeline import make

        make(args.script_json, args.paper_json, args.preview_every)
    elif args.cmd == "publish":
        install_excepthook(strict=True)
        from .publish import publish_episode

        publish_episode(args.episode_dir, args.video_base_url, args.only)
    elif args.cmd == "comments":
        install_excepthook(strict=True)
        from .comments import run

        run(dry_run=args.dry_run)
    elif args.cmd == "refresh-tokens":
        install_excepthook(strict=True)
        from .tokens import refresh_all

        refresh_all()
    elif args.cmd.startswith("review"):
        install_excepthook(strict=True)
        from . import review

        if args.cmd == "review-open":
            review.open_review(args.episode_dir, args.tag)
        elif args.cmd == "review-approved":
            # one "number tag" pair per line, for the workflow to loop over
            for number, tag in review.approved():
                print(f"{number} {tag}")
        elif args.cmd == "review-close":
            review.close(args.number, args.message, args.published)
        else:
            review.skip_unapproved()
    elif args.cmd == "voices":
        from .voices import render_all

        render_all()
    elif args.cmd == "keepalive":
        install_excepthook(strict=True)
        from .tokens import keepalive

        keepalive()


if __name__ == "__main__":
    main()
