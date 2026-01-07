# Estructura Técnica y Responsabilidades: `odoo_blockchain_core`

Este documento detalla la estructura de archivos del módulo y la responsabilidad específica de cada componente. Está dirigido a desarrolladores que necesitan entender o mantener el núcleo del sistema.

## 📂 Árbol de Archivos

```text
odoo_blockchain_core/
├── __init__.py
├── __manifest__.py
│
├── data/
│   └── ir_cron_data.xml      # Definición de tareas programadas (Crons)
├── models/
│   ├── __init__.py
│   ├── abi.py                # Constantes con el ABI del Smart Contract
│   ├── blockchain_config.py  # Extension de res.config.settings
│   ├── blockchain_mixin.py   # Mixin abstracto para uso de terceros
│   └── blockchain_registry_entry.py # Modelo central (Log/Queue)
├── security/
│   ├── ir.model.access.csv   # Permisos de acceso (ACLs)
│   └── security_groups.xml   # Definición de grupos de usuarios
└── views/
    ├── blockchain_menu_views.xml           # Menús principales
    ├── blockchain_registry_entry_views.xml # Vistas de lista/form del log
    └── res_config_settings_views.xml       # Vista de configuración
```

---

## 📝 Detalle por Archivo

### 1. Raíz (`/`)

- **`__manifest__.py`**: Metadatos del módulo. Define dependencias vitales (`base`, `mail`), dependencias externas (`web3`) y carga los archivos XML/CSV en orden.
- **`README.md`**: Documentación general de alto nivel, instalación y guía rápida de uso.

### 2. Modelos (`/models`)

Esta carpeta contiene la **lógica de negocio** pura.

- **`blockchain_registry_entry.py`**:

  - **Responsabilidad**: Es el corazón del sistema. Actúa como base de datos de auditoría local y cola de mensajes.
  - **Funciones Clave**:
    - `process_blockchain_queue()`: Cron unificado. Procesa tanto **Registros** como **Revocaciones** pendientes si el gas es barato.
    - `check_transaction_receipts()`: Cron que monitorea recibos de transacciones (Confirmación de registro o revocación).
    - `action_register()`: Encola documento para registro.
    - `action_revoke()`: Encola documento para revocación (Solo si ya está confirmado).
    - `action_verify_on_chain_manual()`: Consulta `verifyDocument` en el contrato (Call View).
    - `_post_to_related_chatter()`: Helper para escribir confirmar/error en el muro del documento origen.

- **`blockchain_mixin.py`**:

  - **Responsabilidad**: Interfaz "Plug & Play" para otros desarrolladores.
  - **Funciones Clave**:
    - `_compute_blockchain_hash()`: Método abstracto (Hash del dato o del archivo).
    - `action_blockchain_register()`: Wrapper seguro para crear la entrada.
    - `action_blockchain_revoke()`: Wrapper para solicitar revocación.
    - `_post_blockchain_message()`: Escribe en el chatter del modelo heredero.

- **`blockchain_config.py`**:

  - **Responsabilidad**: Gestionar la configuración global del sistema en `res.config.settings`.
  - **Detalle**: Almacena URL del RPC, Contract Address y Chain ID. Verifica la presencia de la variable de entorno `ODOO_BLOCKCHAIN_PRIVATE_KEY` pero **NO** la guarda en BD.

- **`abi.py`**:
  - **Responsabilidad**: Contiene la definición JSON (Application Binary Interface) del contrato `UniversalDocumentRegistry`. Es necesario para que la librería `web3.py` sepa cómo codificar las llamadas al contrato.

### 3. Vistas (`/views`)

Definen la interfaz de usuario (Backend).

- **`blockchain_registry_entry_views.xml`**:
  - Define cómo se ve el log de transacciones (`tree` y `form`). Muestra estado, hash, link al documento original y mensajes de error.
- **`res_config_settings_views.xml`**:
  - Añade la sección "Blockchain Core" al panel de control general de Odoo.
- **`blockchain_menu_views.xml`**:
  - Crea la estructura de menús (Odoo > Ajustes > Técnico > Blockchain) para acceder a los registros.

### 4. Datos y Cron (`/data`)

- **`ir_cron_data.xml`**:
  - Programa la ejecución automática de los métodos Python definidos en `models`.
  - **Cron 1**: Procesa la cola de envío (default: cada 5 min).
  - **Cron 2**: Verifica recibos/confirmaciones (default: cada 10 min).

### 5. Seguridad (`/security`)

- **`security_groups.xml`**: Crea el grupo "Blockchain Manager". Solo los usuarios en este grupo pueden ver menús técnicos y configuraciones.
- **`ir.model.access.csv`**: Reglas estrictas de lectura/escritura. Normalmente, los usuarios normales solo pueden "leer" sus registros de blockchain, pero solo el sistema (sudo) o el Manager pueden crear/editar configuraciones críticas.

---

## 🔄 Flujo de Datos entre Archivos

1.  Usuario pulsa botón en Factura -> **`blockchain_mixin.py`** calcula hash.
2.  Mixin crea registro en **`blockchain_registry_entry.py`** (Estado: Pending).
3.  **`ir_cron_data.xml`** despierta al sistema.
4.  **`blockchain_registry_entry.py`** lee configuración de **`blockchain_config.py`** y usa **`abi.py`** para hablar con la blockchain.
5.  Resultado se actualiza en la vista definida en **`blockchain_registry_entry_views.xml`**.
