.DEFAULT_GOAL := help

.PHONY: help setup update doctor test
help:
	@printf '%s\n' 'make setup   Install or update the runtime and guide authentication (ISSUE_AGENT=, PR_REVIEW_AGENT=claude|codex|cursor)' 'make update  From this clone on main: fast-forward, offer consented native tool upgrades, rerun setup and doctor' 'make doctor  Check installation, authentication, and current Herdr context' 'make test    Run isolated tests with mocked external tools'

setup:
	@./scripts/setup.sh

update:
	@./scripts/update.sh

doctor:
	@./scripts/doctor.sh

test:
	@python3 -B -m unittest discover -s tests -p 'test_*.py' -v
