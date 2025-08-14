def main() -> None:
    # Basic import smoke test
    try:
        import receiptquest  # noqa: F401
        print("Imported 'receiptquest' successfully.")
    except Exception as exc:
        print(f"Failed to import 'receiptquest': {exc}")
        raise


if __name__ == "__main__":
    main()


