"""Pokretanje:

  python -m scraper run        redovno (svakih 20 min); --force ignorira radno vrijeme
  python -m scraper pregled    pregledni izvještaj cijelog područja (bez promjene stanja)
  python -m scraper test       probna poruka na Telegram i probni mail
  python -m scraper tjedni     tjedni izvještaj mailom
  python -m scraper gumbi      proba gumba "Ne zanima me" (4 minute čeka pritiske)

Opcije: --db state.db  --out out  --izvori nekretnine_hr,fina  --bez-slanja
        --uredjaj redmi   (na Redmiju: izvori označeni s "redmi" u config.yaml)
        --redmi-db redmi.db   (na GitHubu: stanje s Redmija za nadzor i tjedni izvještaj)
        --vidjeni seen.json.gz   (na Redmiju: već viđeni oglasi s GitHuba)
        --cijene cijene.json   (na Redmiju: medijani traženih cijena s GitHuba)
        --rezerva   (GitHubov raspored: radi samo ako glavni okidač, cron-job.org, kasni)
"""

import argparse
from pathlib import Path

from .runner import Runner


def main() -> None:
    parser = argparse.ArgumentParser(prog="scraper", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("naredba", choices=["run", "pregled", "test", "tjedni", "gumbi"])
    parser.add_argument("--db", default="state.db", type=Path)
    parser.add_argument("--out", default="out", type=Path)
    parser.add_argument("--izvori", default="", help="samo ovi izvori, odvojeni zarezom")
    parser.add_argument("--bez-slanja", action="store_true", help="ne šalji ništa na Telegram ni mail")
    parser.add_argument("--force", action="store_true", help="radi i izvan radnog vremena")
    parser.add_argument("--uredjaj", default="github", choices=["github", "redmi"])
    parser.add_argument("--redmi-db", type=Path, default=None)
    parser.add_argument("--vidjeni", type=Path, default=None)
    parser.add_argument("--cijene", type=Path, default=None)
    parser.add_argument("--rezerva", action="store_true", help="samo ako zadnje pokretanje kasni")
    args = parser.parse_args()
    only = [s.strip() for s in args.izvori.split(",") if s.strip()] or None
    runner = Runner(args.db, args.out, send=not args.bez_slanja, only=only,
                    device=args.uredjaj, redmi_db=args.redmi_db, seen_file=args.vidjeni,
                    prices_file=args.cijene)
    if args.naredba == "run":
        runner.run(force=args.force, reserve=args.rezerva)
    elif args.naredba == "pregled":
        runner.review()
    elif args.naredba == "test":
        runner.test()
    elif args.naredba == "gumbi":
        runner.button_test()
    else:
        runner.weekly()


if __name__ == "__main__":
    main()
