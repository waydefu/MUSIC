# Security Policy

AURORA is a public desktop audio project. Security reports should be handled privately whenever possible.

## Supported versions

| Version | Security support |
|---|---|
| Current `main` | Supported |
| Latest published release | Supported |
| Older releases / historical commits | Not supported |

A fix may land on `main` before a new installer or release is published.

## Reporting a vulnerability

**Do not post exploit details, proof-of-concept payloads, secrets, or sensitive reproduction steps in a public Issue, Pull Request, Discussion, or commit message.**

Preferred reporting path:

1. Use GitHub's private vulnerability reporting / Security Advisory flow for this repository when available.
2. Include only the information needed to reproduce and assess the issue privately:
   - affected release, tag, or commit;
   - operating system and relevant environment;
   - impact and realistic attack preconditions;
   - minimal reproduction steps;
   - proof of concept, if needed;
   - known mitigations or workarounds.
3. If GitHub does not offer a private reporting channel, open a **minimal public Issue titled `Security contact request`** without vulnerability details and ask the maintainer for a private channel.

There is no guaranteed response-time SLA. Please avoid public disclosure until the maintainer has had a reasonable opportunity to assess and remediate the issue.

## In scope

Examples include:

- arbitrary code execution or unsafe command execution;
- path traversal, unsafe file handling, or unintended file overwrite/deletion;
- privilege or trust-boundary violations;
- unsafe handling of untrusted media, metadata, playlists, or imported data;
- packaging / installer issues with security impact;
- CI/CD, dependency, credential, token, or supply-chain vulnerabilities;
- vulnerabilities in bundled or directly used third-party dependencies when they materially affect AURORA.

## Out of scope

These are normally not security vulnerabilities by themselves:

- audio quality, loudness, HRTF, spatial naturalness, or DSP tuning issues;
- UI/UX bugs without a security impact;
- performance regressions or crashes that do not cross a trust boundary;
- unsupported historical releases;
- generic hardening suggestions without a concrete security impact.

## Disclosure

When practical, fixes should be developed privately before public disclosure. After remediation, the project may publish a security advisory describing affected versions, impact, remediation, and upgrade guidance.
