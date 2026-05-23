# Engineering Norms

## Development Method: SPDD (Structured-Prompt-Driven Development)

Every feature follows this sequence:
1. Story (user story, acceptance criteria)
2. Analysis (SPDD analysis of requirements)
3. REASONS Canvas (structured prompt)
4. Code generation
5. Tests
6. Verification
7. Documentation update

**Never generate production code before Story, Analysis and REASONS Canvas are aligned.**

## Code Quality Standards

### Typing
- Use typed models everywhere (Pydantic for data, type hints for functions)
- Full type annotations on function signatures
- Use Union/Optional explicitly

### Testing
- **Mandatory for all risk rules** (not optional)
- pytest framework
- Use pytest fixtures for setup
- Test both happy path and rejections
- Mock external dependencies

### Logging
- Structured logging (JSON format preferred)
- Log every signal (received, validated, decision)
- Include trace IDs for request tracking
- Log rejection reasons with context

### Error Handling
- Use domain-specific exceptions
- Return meaningful HTTP status codes
- Include error reason in response
- Log exceptions with full context

## Repository Practices

### Secrets
- Never commit API keys, secrets, or credentials
- Use environment variables only
- Document required env vars in README
- Use .gitignore for .env files

### Code Organization
- Separate concerns: models, services, endpoints, repos
- Single responsibility per module
- Clear imports and dependencies
- Avoid circular imports

### Documentation
- Document every important decision (in CLAUDE.md or code comments)
- API endpoints documented
- Risk rules explained
- Configuration options documented

## Git Workflow
- Feature branches (never commit to main)
- Clear commit messages
- Code review before merge
- Tests passing before merge
