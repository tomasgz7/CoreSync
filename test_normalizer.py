from agent.normalizer import DataNormalizer

def run_test():
    # Test case: typical dirty data ingested from an Enterprise Systems HR Database
    raw_data = {
        "dni": "12.345.678",
        "name": "   GARCÍA, juan  "
    }

    print("--- Testing CoreSync Normalizer ---")

    # Processing
    normalized = DataNormalizer.normalize_record(raw_data)

    # Output
    print(f"Original:   {raw_data}")
    print(f"Normalized: {normalized}")

    # Quick assertion
    if normalized['dni'] == '12345678' and normalized['name'] == 'Garcia Juan':
        print("\n[SUCCESS] Normalization completed successfully.")
    else:
        print("\n[ERROR] Normalization produced an unexpected result.")

if __name__ == "__main__":
    run_test()