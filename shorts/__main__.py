"""CLI: python -m shorts <command>

  make              pick a paper and build out/<episode>/video.mp4 (no uploads)
  publish DIR       upload an episode folder to YouTube, Instagram, Threads; record history
  delete-posts EP   delete an episode's posts on every platform and drop it from history
  comments          triage and answer new comments on recent episodes
  suggest-replies   email the owner drafted replies for related Threads posts (never posts)
  refresh-tokens    renew Instagram/Threads long-lived tokens and store them as repo secrets
  review-*          owner review issue: open / list approved / close / skip unapproved / classify
  revise EP_JSON    apply the owner's feedback ($COMMENT): rewrite the script, re-render the videos
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
    m.add_argument("--episode-json", type=Path, help="remake an existing episode (same paper and script)")
    pb = sub.add_parser("publish")
    pb.add_argument("episode_dir", type=Path)
    pb.add_argument("--video-base-url", required=True,
                    help="Public URL prefix of the release assets video_zh.mp4 / video_en.mp4")
    pb.add_argument("--only", nargs="*", choices=["youtube", "instagram", "threads"])
    pb.add_argument("--langs", nargs="*", choices=["zh", "en", "pt"], help="publish only these videos")
    dp = sub.add_parser("delete-posts", help="delete an episode's posts on every platform")
    dp.add_argument("episode")
    sr = sub.add_parser("suggest-replies")
    sr.add_argument("--dry-run", action="store_true")
    c = sub.add_parser("comments")
    c.add_argument("--dry-run", action="store_true", help="classify only; post, hide, and email nothing")
    sub.add_parser("refresh-tokens")
    sub.add_parser("keepalive")
    vo = sub.add_parser("voices")
    vo.add_argument("--lang", nargs="*", choices=["zh", "en", "pt"])
    sub.add_parser("test-email")
    ro = sub.add_parser("review-open")
    ro.add_argument("episode_dir", type=Path)
    ro.add_argument("tag")
    sub.add_parser("review-approved")
    rc = sub.add_parser("review-close")
    rc.add_argument("number", type=int)
    rc.add_argument("--message", required=True)
    rc.add_argument("--published", action="store_true")
    rc.add_argument("--keep-open", action="store_true", help="only comment (a later run retries)")
    sub.add_parser("review-skip-unapproved")
    sub.add_parser("review-kind", help="classify the comment in $COMMENT: approve / reject / feedback")
    rt = sub.add_parser("review-tag")
    rt.add_argument("number", type=int)
    rv = sub.add_parser("revise", help="apply the feedback in $COMMENT to an episode and re-render it")
    rv.add_argument("episode_json", type=Path)
    rv.add_argument("--changes-out", type=Path, required=True)
    rr = sub.add_parser("review-revised")
    rr.add_argument("number", type=int)
    rr.add_argument("episode_dir", type=Path)
    rr.add_argument("tag")
    rr.add_argument("changes", type=Path)
    rr.add_argument("--version", default="")
    rm = sub.add_parser("review-comment")
    rm.add_argument("number", type=int)
    rm.add_argument("--message", required=True)
    args = ap.parse_args()

    if args.cmd == "make":
        install_excepthook(strict=False)
        from .pipeline import make

        make(args.script_json, args.paper_json, args.preview_every, args.episode_json)
    elif args.cmd == "publish":
        install_excepthook(strict=True)
        from .publish import publish_episode

        publish_episode(args.episode_dir, args.video_base_url, args.only, args.langs)
    elif args.cmd == "delete-posts":
        install_excepthook(strict=True)
        from .publish import delete_episode

        delete_episode(args.episode)
    elif args.cmd == "comments":
        install_excepthook(strict=True)
        from .comments import run

        run(dry_run=args.dry_run)
    elif args.cmd == "suggest-replies":
        install_excepthook(strict=True)
        from .engage import run as suggest

        suggest(dry_run=args.dry_run)
    elif args.cmd == "refresh-tokens":
        install_excepthook(strict=True)
        from .tokens import refresh_all

        refresh_all()
    elif args.cmd == "revise":
        install_excepthook(strict=False)
        import os

        from .pipeline import revise

        _, changes = revise(args.episode_json, os.environ["COMMENT"])
        args.changes_out.write_text(changes + "\n", encoding="utf-8")
    elif args.cmd.startswith("review"):
        install_excepthook(strict=True)
        from . import review

        if args.cmd == "review-open":
            review.open_review(args.episode_dir, args.tag)
        elif args.cmd == "review-approved":
            # one "number tag" pair per line, for the workflow to loop over
            for number, tag in review.approved():
                print(f"{number} {tag}")
        elif args.cmd == "review-kind":
            import os

            print(review.kind(os.environ.get("COMMENT", "")))
        elif args.cmd == "review-tag":
            print(review.tag_of(args.number))
        elif args.cmd == "review-revised":
            review.post_revision(args.number, args.episode_dir, args.tag,
                                 args.changes.read_text(encoding="utf-8").strip(), args.version)
        elif args.cmd == "review-comment":
            review.comment(args.number, args.message)
        elif args.cmd == "review-close":
            review.close(args.number, args.message, args.published, args.keep_open)
        else:
            review.skip_unapproved()
    elif args.cmd == "test-email":
        install_excepthook(strict=True)
        from .notify import _smtp

        ok = _smtp("[行為解碼] 測試信 Test email",
                   "這是一封測試信。之後需要你親自處理的留言會寄到這裡。\n"
                   "This is a test. Comments that need you will be sent here.")
        raise SystemExit(0 if ok else "Test email was not sent (check the ALERT_EMAIL_* secrets)")
    elif args.cmd == "voices":
        from .voices import render_all

        render_all(args.lang)
    elif args.cmd == "keepalive":
        install_excepthook(strict=True)
        from .tokens import keepalive

        keepalive()


if __name__ == "__main__":
    main()
