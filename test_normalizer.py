from agent.normalizer import DataNormalizer

def run_test():
    # Caso de prueba: Datos "sucios" típicos de una base de datos de Simulation Center
    raw_data = {
        "dni": "12.345.678", 
        "name": "  GARCÍA, juan  "
    }
    
    print("--- Probando CoreSync Normalizer ---")
    
    # Procesamiento
    normalized = DataNormalizer.normalize_record(raw_data)
    
    # Salida
    print(f"Original: {raw_data}")
    print(f"Normalizado: {normalized}")
    
    # Verificación rápida
    if normalized['dni'] == '12345678' and normalized['name'] == 'Garcia Juan':
        print("\n[SUCCESS] Normalización exitosa.")
    else:
        print("\n[ERROR] Algo no salió como se esperaba.")

if __name__ == "__main__":
    run_test()