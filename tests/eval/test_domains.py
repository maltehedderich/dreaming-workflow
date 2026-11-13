"""Where facts land in the index: projects as subdomains, other areas as domains."""

from datetime import UTC, datetime
from pathlib import Path

from dreaming_workflow.memory.index import same_name
from tests.eval.harness import (
    Checks,
    EvalRun,
    RunInput,
    ScenarioRunner,
    citing,
    empty_memory,
    headings,
)
from tests.support.memory import project_memory
from tests.support.sessions import (
    ALPHA_SESSION_ID,
    BETA_SESSION_ID,
    GAMMA_SESSION_ID,
    PRICING_SESSION_ID,
    alpha_session,
    beta_session,
    gamma_session,
    pricing_session,
)

type Heading = tuple[str, str | None]


def _two_projects_and_pricing(directory: Path) -> RunInput:
    sessions = directory / "sessions"
    return RunInput(
        empty_memory(directory),
        session_files=(
            alpha_session(
                sessions / "alpha.jsonl", start=datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
            ),
            beta_session(
                sessions / "beta.jsonl", start=datetime(2026, 11, 4, 14, 0, tzinfo=UTC)
            ),
            pricing_session(
                sessions / "pricing.jsonl",
                start=datetime(2026, 11, 5, 16, 0, tzinfo=UTC),
            ),
        ),
    )


def _new_project(directory: Path) -> RunInput:
    memory = directory / "memory"
    project_memory(memory)
    session = gamma_session(
        directory / "sessions" / "gamma.jsonl",
        start=datetime(2026, 11, 5, 11, 0, tzinfo=UTC),
    )
    return RunInput(memory, session_files=(session,))


def _placement(run: EvalRun, session_id: str) -> dict[str, Heading | None]:
    """Each file citing the session, and the index heading it's listed under."""
    index = run.index()
    listed = headings(index) if index else {}
    return {slug: listed.get(slug) for slug in sorted(citing(run.notes(), session_id))}


def _listed(placement: dict[str, Heading | None]) -> list[Heading] | None:
    """The headings, or None if a file has no entry or there are no files."""
    found = [heading for heading in placement.values() if heading is not None]
    if not placement or len(found) != len(placement):
        return None
    return found


def _describe(**placements: dict[str, Heading | None]) -> str:
    return "; ".join(
        f"{name}: {placement or 'no files'}" for name, placement in placements.items()
    )


def test_projects_share_a_domain_and_business_gets_its_own(
    runner: ScenarioRunner, checks: Checks
) -> None:
    for run in runner.three_times(_two_projects_and_pricing):
        checks.check(
            run,
            "all three sessions analyzed",
            run.report.analyzed == 3,
            f"analyzed {run.report.analyzed}",
        )
        alpha = _placement(run, ALPHA_SESSION_ID)
        beta = _placement(run, BETA_SESSION_ID)
        pricing = _placement(run, PRICING_SESSION_ID)
        detail = _describe(alpha=alpha, beta=beta, pricing=pricing)
        alpha_headings = _listed(alpha)
        beta_headings = _listed(beta)
        pricing_headings = _listed(pricing)

        project_domain: str | None = None
        if alpha_headings and beta_headings:
            projects = alpha_headings + beta_headings
            domains = {domain for domain, _ in projects}
            alpha_subdomains = {subdomain for _, subdomain in alpha_headings}
            beta_subdomains = {subdomain for _, subdomain in beta_headings}
            if (
                len(domains) == 1
                and None not in alpha_subdomains | beta_subdomains
                and not alpha_subdomains & beta_subdomains
            ):
                [project_domain] = domains
        checks.check(
            run,
            "alpha and beta under different ### of the same ##",
            project_domain is not None,
            detail,
        )
        checks.check(
            run,
            "pricing under a different ##",
            project_domain is not None
            and pricing_headings is not None
            and not any(
                same_name(domain, project_domain) for domain, _ in pricing_headings
            ),
            detail,
        )
    checks.done()


def test_new_project_gets_a_subdomain_in_the_existing_domain(
    runner: ScenarioRunner, checks: Checks
) -> None:
    for run in runner.three_times(_new_project):
        checks.check(
            run,
            "session analyzed",
            run.report.analyzed == 1,
            f"analyzed {run.report.analyzed}",
        )
        gamma = _placement(run, GAMMA_SESSION_ID)
        gamma_headings = _listed(gamma)
        before = run.index(before=True)
        after = run.index()
        known = (
            {
                subdomain.name
                for domain in before.domains
                for subdomain in domain.subdomains
            }
            if before
            else set()
        )
        subdomains = {subdomain for _, subdomain in gamma_headings or []}
        checks.check(
            run,
            "gamma's files in one new ### under ## Development",
            gamma_headings is not None
            and all(same_name(domain, "Development") for domain, _ in gamma_headings)
            and len(subdomains) == 1
            and all(
                subdomain is not None
                and not any(same_name(subdomain, name) for name in known)
                for subdomain in subdomains
            ),
            _describe(gamma=gamma),
        )
        domains_before = (
            sorted(d.name.casefold() for d in before.domains) if before else []
        )
        domains_after = (
            sorted(d.name.casefold() for d in after.domains) if after else []
        )
        checks.check(
            run,
            "no ## heading added",
            domains_after == domains_before,
            f"before {domains_before}, after {domains_after}",
        )
    checks.done()
