# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| latest  | :white_check_mark: |
| < 1.0   | :white_check_mark: |

## Reporting a Vulnerability

**Please do NOT report security vulnerabilities through public GitHub issues.**

Instead, please report them responsibly via email:

📧 **security@serverless-sandbox.com**

### What to Include

When reporting a vulnerability, please include:

- A description of the vulnerability
- Steps to reproduce the issue
- Potential impact
- Any suggested fix (if applicable)

### Response Timeline

| Action | Timeframe |
|--------|-----------|
| Acknowledgment of report | Within **48 hours** |
| Initial assessment | Within **5 business days** |
| Fix development & testing | Within **30 days** (critical), **90 days** (non-critical) |
| Public disclosure | After fix is released |

### Process

1. You report the vulnerability via the email above
2. We acknowledge receipt and begin investigation
3. We work with you to understand and validate the issue
4. We develop and test a fix
5. We release the fix and publish a security advisory
6. We credit you in the advisory (unless you prefer anonymity)

## Security Best Practices for Users

- Keep `serverless-sandbox` updated to the latest version
- Never commit API keys, tokens, or credentials to your repository
- Use environment variables or the SDK's keychain for authentication
- Review sandbox templates before deploying to production

## Scope

This security policy applies to the `serverless-sandbox` Python package and CLI tool. For issues related to the underlying Alibaba Cloud FC service, please contact [Alibaba Cloud Security](https://security.alibaba.com/).

Thank you for helping keep Serverless Sandbox and its users safe! 🔒
