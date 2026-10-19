"""The desktop window.

Nothing is decided here. Every button calls `service`, which the command line
also calls, so the two cannot disagree about what a number means. This module
is only responsible for asking, showing and complaining.

tkinter is used because it ships with Python: a person who downloads a built
application should not need anything, and a person running from source should
not need a package manager either.
"""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox, ttk

from . import reports, service, spreadsheet, statline

TITLE = "OOTP Scout"

COLUMNS = [
    ("rank", "#", 45),
    ("name", "Player", 165),
    ("team", "Team", 120),
    ("position", "Pos", 45),
    ("age", "Age", 45),
    ("grade", "Grade", 55),
    ("implied", "Implied", 65),
    ("gap", "+/-", 50),
    ("war", "WAR", 60),
    ("expected", "Expected", 70),
    ("diff", "Diff", 60),
    ("z", "z", 50),
    ("scouting", "Scouting", 90),
    ("seen", "Seen", 85),
]

# Row tints, matching the spreadsheet so the two read alike.
TAGS = {
    "strong_up": "#c7efce",
    "notable_up": "#fff2cc",
    "notable_down": "#fce4d6",
    "strong_down": "#ffc7ce",
}


class ScoutWindow(tk.Tk):
    def __init__(self, db: str | None = None):
        super().__init__()
        self.db = db
        self.title(TITLE)
        self.geometry("1180x680")
        self.minsize(900, 500)

        self._results: list = []
        self._sort_column = None
        self._sort_reverse = False
        self._work: queue.Queue = queue.Queue()
        self._alive = True
        self._pump = None
        self._busy = 0

        self._build_toolbar()
        self._build_filters()
        self._build_table()
        self._build_status()

        # Closing the window has to stop the pump. Otherwise the next tick
        # fires at widgets that are already gone, and Tcl complains about a
        # command name rather than anything a reader could act on.
        self.bind("<Destroy>", self._stopping)

        self._pump = self.after(100, self._drain)
        self.after(200, self.refresh_sources)

    def _stopping(self, event):
        if event.widget is not self:
            return
        self._alive = False
        if self._pump is not None:
            self.after_cancel(self._pump)
            self._pump = None

    # --- layout -------------------------------------------------------------

    def _build_toolbar(self):
        bar = ttk.Frame(self, padding=(10, 8))
        bar.pack(fill="x")

        ttk.Button(bar, text="Import latest export",
                   command=self.import_latest).pack(side="left")
        ttk.Button(bar, text="Import a file…",
                   command=self.import_file).pack(side="left", padx=(6, 0))
        ttk.Label(bar, text="Tag").pack(side="left", padx=(16, 4))
        self.tag_entry = ttk.Entry(bar, width=16)
        self.tag_entry.pack(side="left")

        ttk.Button(bar, text="Export to spreadsheet…",
                   command=self.export_spreadsheet).pack(side="right")
        ttk.Button(bar, text="Trade…",
                   command=self.open_trade).pack(side="right", padx=(0, 6))
        ttk.Button(bar, text="Player history…",
                   command=self.open_history).pack(side="right", padx=(0, 6))
        ttk.Button(bar, text="Standings",
                   command=self.open_standings).pack(side="right", padx=(0, 6))

    def _build_filters(self):
        top = ttk.Frame(self, padding=(10, 0, 10, 4))
        top.pack(fill="x")
        bottom = ttk.Frame(self, padding=(10, 0, 10, 8))
        bottom.pack(fill="x")

        def label(parent, text):
            ttk.Label(parent, text=text).pack(side="left", padx=(0, 4))

        label(top, "League")
        self.league = ttk.Combobox(top, width=20, state="readonly")
        self.league.pack(side="left", padx=(0, 12))
        self.league.bind("<<ComboboxSelected>>",
                         lambda _e: self.refresh_choices())

        label(top, "Team")
        self.team = ttk.Combobox(top, width=24, state="readonly")
        self.team.pack(side="left", padx=(0, 12))

        label(top, "Ratings")
        self.mode = ttk.Combobox(top, width=10, state="readonly",
                                 values=["current", "potential"])
        self.mode.set("current")
        self.mode.pack(side="left", padx=(0, 12))

        label(top, "Role")
        self.role = ttk.Combobox(top, width=9, state="readonly",
                                 values=["all", "batter", "pitcher"])
        self.role.set("all")
        self.role.pack(side="left")

        label(bottom, "Group")
        self.tag = ttk.Combobox(bottom, width=20, state="readonly")
        self.tag.pack(side="left", padx=(0, 12))

        label(bottom, "Seen")
        self.seen = ttk.Combobox(bottom, width=14, state="readonly",
                                 values=list(service.SEEN_WINDOWS))
        self.seen.set("any time")
        self.seen.pack(side="left", padx=(0, 12))

        label(bottom, "Ignore below")
        self.floor = ttk.Spinbox(bottom, width=5, from_=0, to=100, increment=5)
        self.floor.set(0)
        self.floor.pack(side="left", padx=(0, 12))

        label(bottom, "Find")
        self.find = ttk.Entry(bottom, width=18)
        self.find.pack(side="left", padx=(0, 12))
        # Filtering by name only hides rows, so it needs no refit - redrawing
        # from the findings already in hand is instant.
        self.find.bind("<KeyRelease>", lambda _e: self._redraw())

        ttk.Button(bottom, text="Show", command=self.refresh_ranking).pack(
            side="left")

    def _build_table(self):
        frame = ttk.Frame(self, padding=(10, 0))
        frame.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(frame, columns=[c[0] for c in COLUMNS],
                                 show="headings", selectmode="browse")
        for key, heading, width in COLUMNS:
            self.tree.heading(key, text=heading,
                              command=lambda k=key: self.sort_by(k))
            self.tree.column(key, width=width,
                             anchor="w" if key in ("name", "team", "scouting")
                             else "center")
        for name, colour in TAGS.items():
            self.tree.tag_configure(name, background=colour)

        self.tree.bind("<Double-1>", lambda _e: self.open_card())
        self.tree.bind("<Return>", lambda _e: self.open_card())

        vertical = ttk.Scrollbar(frame, orient="vertical",
                                 command=self.tree.yview)
        self.tree.configure(yscrollcommand=vertical.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vertical.pack(side="right", fill="y")

    def _build_status(self):
        self.status = tk.StringVar(value="Import an export to begin.")
        bar = ttk.Frame(self, padding=(10, 6))
        bar.pack(fill="x")
        ttk.Label(bar, textvariable=self.status, anchor="w").pack(fill="x")

    # --- background work ----------------------------------------------------

    def _run(self, work, done, busy="Working…"):
        """Run `work` off the UI thread; call `done(result)` back on it.

        A league-sized fit takes long enough to freeze the window, and a frozen
        window reads as a crash.
        """
        if not self._alive:
            return
        self.status.set(busy)
        self.config(cursor="watch")
        self._busy += 1

        def worker():
            try:
                self._work.put((done, work(), None))
            except Exception as error:                       # noqa: BLE001
                self._work.put((done, None, error))

        threading.Thread(target=worker, daemon=True).start()

    def _drain(self):
        if not self._alive:
            return
        try:
            while True:
                done, result, error = self._work.get_nowait()
                self._busy -= 1
                self.config(cursor="")
                if error is not None:
                    self._complain(error)
                else:
                    done(result)
        except queue.Empty:
            pass
        self._pump = self.after(100, self._drain)

    def _complain(self, error: Exception):
        if isinstance(error, service.ScoutError):
            self.status.set(str(error))
            messagebox.showinfo(TITLE, str(error))
            return
        self.status.set(f"{type(error).__name__}: {error}")
        messagebox.showerror(TITLE, f"{error}\n\n{traceback.format_exc()}")

    # --- actions ------------------------------------------------------------

    def refresh_sources(self):
        def work():
            return service.leagues(self.db)

        def done(held):
            names = [e["league"] for e in held]
            self.league["values"] = names
            if names and not self.league.get():
                self.league.set(names[0])
            self.refresh_choices()
            if names:
                self.refresh_ranking()
            else:
                self.status.set("Nothing stored yet - import an export.")

        self._run(work, done, "Reading the database…")

    def refresh_choices(self):
        """Repopulate the per-league pickers. Teams and groups both move."""
        league = self.league.get() or None

        held = service.tags(league, self.db)
        self.tag["values"] = ["(everyone)"] + [f"{t}  ({n})" for t, n in held]
        if self.tag.get() not in self.tag["values"]:
            self.tag.set("(everyone)")

        clubs = service.teams(league, self.db)
        self.team["values"] = (["(all teams)"]
                               + [f"{t}  ({n})" for t, n in clubs])
        if self.team.get() not in self.team["values"]:
            self.team.set("(all teams)")

    def import_latest(self):
        try:
            found = reports.find_latest()
        except FileNotFoundError as error:
            messagebox.showinfo(TITLE, str(error))
            return
        self._import(found.path)

    def import_file(self):
        path = filedialog.askopenfilename(
            title="Choose an OOTP report",
            filetypes=[("OOTP reports", "*.html *.htm *.tsv *.csv"),
                       ("All files", "*.*")])
        if path:
            self._import(path)

    def _import(self, path):
        tag = self.tag_entry.get().strip()

        def work():
            return service.import_export(path, tag=tag, db=self.db)

        def done(result):
            self.status.set(
                f"{result.view_name}: {result.players} players on the "
                f"{result.scale} scale - {result.added} new, "
                f"{result.updated} updated in {result.league!r}"
                + (f", tagged {result.tag!r}" if result.tag else ""))
            if result.skipped:
                messagebox.showinfo(
                    TITLE,
                    f"{len(result.skipped)} row(s) were not projected:\n\n"
                    + "\n".join(f"{n}: {d}" for n, d in result.skipped[:12]))
            self.league.set(result.league)
            self.refresh_sources()

        self._run(work, done, f"Reading {os.path.basename(path)}…")

    def refresh_ranking(self):
        options = self._filters()

        def work():
            return service.rank(**options)

        def done(result):
            self._results = result.findings
            self._fill(result)

        self._run(work, done, "Fitting…")

    def _filters(self) -> dict:
        """What the filter row currently says, as service.rank wants it.

        Not named _options: tkinter.Misc._options is real, config() calls
        it, and shadowing it breaks every widget update in the window.
        """
        try:
            floor = float(self.floor.get())
        except ValueError:
            floor = 0.0
        role = self.role.get()
        seen = self.seen.get()
        return {
            "league": self.league.get() or None,
            "mode": self.mode.get() or None,
            "role": None if role == "all" else role,
            "team": self._chosen(self.team, "(all teams)"),
            "tag": self._chosen(self.tag, "(everyone)"),
            "seen": seen if seen in service.SEEN_WINDOWS else None,
            "min_grade": floor if floor > 0 else None,
            "db": self.db,
        }

    @staticmethod
    def _chosen(box, placeholder: str) -> str | None:
        """A picker's value without the count the label carries."""
        value = box.get().strip()
        if not value or value == placeholder:
            return None
        return value.rsplit("  (", 1)[0].strip() or None

    def _fill(self, result: service.RankingResult):
        self._result = result
        self._redraw()

        summary = (f"{result.league} - {result.grade_label} - "
                   f"{result.shown} shown, fitted on {result.fitted_on}")
        for fit in result.fits:
            summary += (f"   |   {fit.group}: {fit.count} players, "
                        f"{fit.slope:+.3f} WAR per point")
        if result.notes:
            summary += "   |   " + "  ".join(result.notes)
        self.status.set(summary)

    def _redraw(self):
        """Put the findings in hand on screen, minus anything Find excludes.

        Rank numbers stay those of the full ranking: a player is the 14th most
        underrated in his league whether or not the other thirteen are on
        screen, and renumbering him 1 would say something untrue.
        """
        result = getattr(self, "_result", None)
        self.tree.delete(*self.tree.get_children())
        if result is None:
            return
        wanted = self.find.get().strip().lower()
        for rank, finding in enumerate(result.findings, start=1):
            subject = finding.subject
            if wanted and wanted not in subject.name.lower():
                continue
            implied = ("" if finding.implied_grade is None
                       else f"{finding.implied_grade:.0f}")
            gap = "" if finding.grade_gap is None else f"{finding.grade_gap:+.0f}"
            tint = self._tint(finding.z_score)
            self.tree.insert(
                "", "end", tags=((tint,) if tint else ()),
                values=(rank, subject.name, subject.meta.get("team", ""),
                        subject.position, subject.meta.get("age", ""),
                        f"{subject.grade:.0f}", implied, gap,
                        f"{subject.war:.2f}", f"{finding.expected_war:.2f}",
                        f"{finding.residual:+.2f}", f"{finding.z_score:.2f}",
                        finding.scouting_accuracy,
                        subject.meta.get("seen", "")))

    @staticmethod
    def _tint(z: float) -> str:
        if z >= spreadsheet.STRONG_Z:
            return "strong_up"
        if z >= spreadsheet.NOTABLE_Z:
            return "notable_up"
        if z <= -spreadsheet.STRONG_Z:
            return "strong_down"
        if z <= -spreadsheet.NOTABLE_Z:
            return "notable_down"
        return ""

    def sort_by(self, column: str):
        if not self._results:
            return
        numeric = {"rank": lambda f: 0, "grade": lambda f: f.subject.grade,
                   "implied": lambda f: f.implied_grade or -999,
                   "gap": lambda f: f.grade_gap or -999,
                   "war": lambda f: f.subject.war,
                   "expected": lambda f: f.expected_war,
                   "diff": lambda f: f.residual, "z": lambda f: f.z_score,
                   "age": lambda f: int(f.subject.meta.get("age") or 0)}
        text = {"name": lambda f: f.subject.name.lower(),
                "team": lambda f: (f.subject.meta.get("team") or "").lower(),
                "position": lambda f: f.subject.position,
                "scouting": lambda f: f.scouting_accuracy,
                "seen": lambda f: f.subject.meta.get("seen") or ""}
        key = numeric.get(column) or text.get(column)
        if key is None:
            return
        self._sort_reverse = (not self._sort_reverse
                              if self._sort_column == column else
                              column in numeric)
        self._sort_column = column
        self._results = sorted(self._results, key=key,
                               reverse=self._sort_reverse)
        self._result = service.RankingResult(
            league=self.league.get(), mode=self.mode.get(),
            grade_label="POT" if self.mode.get() == "potential" else "OVR",
            findings=self._results, shown=len(self._results))
        self._redraw()

    def export_spreadsheet(self):
        if not self._results:
            messagebox.showinfo(TITLE, "Nothing to export yet.")
            return
        path = filedialog.asksaveasfilename(
            title="Save spreadsheet", defaultextension=".xlsx",
            initialfile="ootp-scout.xlsx",
            filetypes=[("Excel workbook", "*.xlsx"), ("CSV", "*.csv")])
        if not path:
            return
        options = self._filters()
        findings = list(self._results)

        def work():
            result = service.rank(**options)
            columns = sorted({k for f in findings for k in f.subject.ratings})
            spreadsheet.write_xlsx(path, findings, result.fits,
                                   grade_label=result.grade_label,
                                   rating_columns=columns)
            return path

        def done(written):
            self.status.set(f"Wrote {len(findings)} players to {written}")

        self._run(work, done, "Writing the spreadsheet…")

    def open_standings(self):
        """Every team's best roster, totalled into a projected record."""
        league = self.league.get() or None
        seen = self.seen.get()
        if seen not in service.SEEN_WINDOWS or seen == "any time":
            # A roster is a snapshot. Pooling every import a save has ever had
            # would put a traded player on both of his teams at once.
            seen = "newest import"

        def work():
            return service.project_standings(league=league, seen=seen,
                                             db=self.db)

        def done(table):
            lines = [f"{table.league} - projected over {table.games} games", ""]
            lines.append(f"  {'#':>2}  {'Team':<22}{'W':>4}{'L':>5}"
                         f"{'WAR':>7}{'Bat':>7}{'Arm':>7}")
            for place, team in enumerate(table.teams, start=1):
                lines.append(
                    f"  {place:>2}  {team.team[:22]:<22}{team.wins:>4.0f}"
                    f"{team.losses:>5.0f}{team.war:>7.1f}"
                    f"{team.batting_war:>7.1f}{team.pitching_war:>7.1f}")
            lines.append("")
            lines += [f"Note: {note}" for note in table.notes]
            lines.append("")
            lines.append("Every team is assumed to field its best roster and "
                         "stay healthy, so the\nspread here is narrower than "
                         "real standings run.")
            messagebox.showinfo(TITLE, "\n".join(lines))

        self._run(work, done, "Building rosters…")

    def open_card(self):
        """The projected season for the selected player, in full.

        A row in the table is an argument about a player's value; this is the
        evidence behind it - the ERA and innings, or the slash line, that the
        WAR was computed from.
        """
        chosen = self.tree.focus() or (self.tree.selection() or [None])[0]
        if not chosen:
            return
        name = self.tree.item(chosen)["values"][1]
        finding = next((f for f in getattr(self, "_results", [])
                        if f.subject.name == name), None)
        if finding is None:
            return
        subject = finding.subject

        head = [subject.name]
        where = "  ".join(part for part in (
            subject.meta.get("team", ""), subject.position,
            f"age {subject.meta.get('age')}" if subject.meta.get("age") else "",
        ) if part)
        if where:
            head.append(where)

        grade = [f"{self._grade_label()} {subject.grade:.0f}"]
        if finding.implied_grade is not None:
            grade.append(f"implied {finding.implied_grade:.0f}")
        if finding.grade_gap is not None:
            grade.append(f"({finding.grade_gap:+.0f})")
        head.append("  ".join(grade))
        head.append(f"WAR {subject.war:.2f}   expected "
                    f"{finding.expected_war:.2f}   z {finding.z_score:+.2f}")
        if subject.rwar is not None:
            head.append(f"rWAR {subject.rwar:.2f}")
        if finding.scouting_accuracy:
            head.append(f"Scouting accuracy: {finding.scouting_accuracy}")

        lines = ["", "PROJECTED SEASON"]
        pairs = statline.display(subject.projected, subject.is_pitcher)
        if pairs:
            lines += _columns(pairs)
        else:
            lines.append("  Not recorded - re-import this export to store it.")

        if subject.ratings:
            lines += ["", "RATINGS"]
            lines += _columns([(k, v) for k, v in subject.ratings.items() if v])

        messagebox.showinfo(TITLE, "\n".join(head + lines))

    def _grade_label(self) -> str:
        return "POT" if self.mode.get() == "potential" else "OVR"

    def open_history(self):
        name = _ask(self, "Player history", "Player name (or part of one):")
        if not name:
            return

        def work():
            return service.history(name, league=self.league.get() or None,
                                   db=self.db)

        def done(payload):
            rows, matches = payload
            if not rows:
                messagebox.showinfo(TITLE, f"No player matching {name!r}.")
                return
            if len(matches) > 1 and not any(
                    m["name"].strip().lower() == name.strip().lower()
                    for m in matches):
                messagebox.showinfo(
                    TITLE, "Several players match:\n\n"
                    + "\n".join(m["name"] for m in matches[:12]))
                return
            lines = [f"{rows[0]['name']}", ""]
            for row in rows:
                lines.append(
                    f"{row['seen_at'][:10]}  {row['mode']:<10} "
                    f"{(row['position'] or ''):<4} grade "
                    f"{row['grade']:.0f}  WAR {row['war']:.2f}")
            if len(rows) > 1 and rows[0]["grade"] and rows[-1]["grade"]:
                lines += ["", f"Grade {rows[0]['grade']:.0f} -> "
                              f"{rows[-1]['grade']:.0f}"]
            messagebox.showinfo(TITLE, "\n".join(lines))

        self._run(work, done, "Looking up…")

    def open_trade(self):
        give = _ask(self, "Trade", "You give up (comma separated):")
        if give is None:
            return
        get = _ask(self, "Trade", "You receive (comma separated):")
        if get is None:
            return
        options = self._filters()

        def work():
            return service.compare([n for n in give.split(",")],
                                   [n for n in get.split(",")], **options)

        def done(result):
            def side(title, findings):
                lines = [title]
                for f in findings:
                    lines.append(
                        f"   {f.subject.name:<20} {f.subject.position:<3} "
                        f"grade {f.subject.grade:.0f}   WAR "
                        f"{f.subject.war:>6.2f}   diff {f.residual:>+6.2f}")
                return lines or [title + "   (nobody)"]

            war = result["b_war"] - result["a_war"]
            gap = result["b_gap"] - result["a_gap"]
            lines = (side("YOU GIVE UP", result["a"]) + [""]
                     + side("YOU RECEIVE", result["b"]) + ["",
                     f"Projected WAR      {war:+.2f}",
                     f"Versus the grades  {gap:+.2f}", "",
                     "Production only - no salaries are recorded, so this is "
                     "not surplus value."])
            messagebox.showinfo(TITLE, "\n".join(lines))

        self._run(work, done, "Weighing…")


def _columns(pairs, per_row: int = 6) -> list[str]:
    """Label/value pairs laid out in even columns.

    A message box is a monospace-less wall of text otherwise, and a stat line
    read as one long run of numbers is worse than no stat line.
    """
    width = max((len(label) for label, _v in pairs), default=0)
    width = max(width, max((len(str(value)) for _l, value in pairs), default=0))
    lines = []
    for start in range(0, len(pairs), per_row):
        chunk = pairs[start:start + per_row]
        lines.append("  " + "  ".join(f"{label:>{width}}" for label, _v in chunk))
        lines.append("  " + "  ".join(f"{value:>{width}}" for _l, value in chunk))
        lines.append("")
    return lines[:-1] if lines else lines


def _ask(parent, title, prompt) -> str | None:
    from tkinter import simpledialog
    return simpledialog.askstring(title, prompt, parent=parent)


def main(db: str | None = None) -> int:
    ScoutWindow(db).mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
