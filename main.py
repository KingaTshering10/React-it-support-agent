"""Interactive or single-query CLI for the simulated IT-support agent."""
import argparse

from src.agent import build_agent, run_agent


def main():
    parser = argparse.ArgumentParser(description="Azure OpenAI + LangChain mock IT-support agent.")
    parser.add_argument("question", nargs="*", help="Optional one-shot question.")
    parser.add_argument("--read-only", action="store_true", help="Expose only health, incident, and log tools.")
    parser.add_argument("--quiet", action="store_true", help="Hide the post-run tool trace.")
    args = parser.parse_args()
    try:
        agent = build_agent(read_only=args.read_only)
    except ValueError as error:
        print(error)
        return 1
    except Exception:
        print("Unable to initialize the agent. Check dependencies and Azure configuration.")
        return 1

    def query(text):
        try:
            answer = run_agent(agent, text, verbose=not args.quiet)
        except Exception:
            print("Agent run failed. Check Azure access, connectivity, the step limit, and local audit-log permissions.")
            return False
        print("\nFinal answer:\n" + answer)
        return True

    if args.question:
        return 0 if query(" ".join(args.question)) else 1
    print("Mock IT-support agent. Each question is independent. Type exit to quit.")
    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break
        if question.lower() in {"exit", "quit"}:
            break
        if question:
            query(question)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
