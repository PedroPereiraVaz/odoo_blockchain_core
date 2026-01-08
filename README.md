# Odoo Blockchain Core

**Autor:** `Pedro Pereira`

**Versión:** `18.0.1.0.0`

**Categoría:** `Technical/Blockchain`

**Dependencias:** `base`, `mail`

**Librerías Python:** `web3`

Este módulo actúa como el **núcleo de infraestructura** para la integración de Odoo con blockchains compatibles con EVM (Ethereum, Polygon, Sepolia, etc.). Su propósito es abstraer toda la complejidad criptográfica y de gestión de transacciones, permitiendo que cualquier otro módulo funcional de Odoo (Ventas, RRHH, Inventario) pueda "certificar" documentos digitales con una inversión mínima de desarrollo.

---

## 🌎 1. Análisis en Profundidad: ¿Qué hace y por qué?

### ¿Que NO hace este módulo?

- No define _qué_ documentos son importantes.
- No genera PDFs ni visualizaciones.
- No contiene lógica de negocio específica (ej. no sabe lo que es un "Diploma" o una "Factura").

### ¿Qué hace EXACTAMENTE?

1.  **Centralización de Conexión**: Gestiona una única conexión RPC y Wallet para toda la instancia de Odoo.
2.  **Registro Universal (Hash Registry)**: Mantiene un log inmutable de huellas digitales (Hashes SHA-256) en la blockchain.
3.  **Gestión de Gas y Colas**: Implementa un sistema de "Fire & Forget". Los usuarios solicitan el registro, y este módulo decide _cuándo_ enviarlo a la red basándose en el precio del Gas actual, evitando picos de coste.
4.  **Seguridad de Llaves (Key Management)**: Aísla la llave privada del almacenamiento de la base de datos, requiriendo inyección por variables de entorno.
5.  **Revocación On-Chain**: Gestión completa del ciclo de vida, permitiendo revocar documentos inválidos.
6.  **Trazabilidad**: Integración nativa con `mail.thread` para feedback en tiempo real en el documento origen.

> [!NOTE]
> Para una visión técnica más detallada de los archivos y estructura, consulta: **[📄 Estructura Técnica](docs/ESTRUCTURA_TECNICA.md)**

### Arquitectura: ¿Dónde vive la lógica?

El sistema sigue un patrón de diseño **Consumidor-Proveedor**:

- **Proveedor (Este módulo)**: Expone un `Mixin` (`blockchain.certified.mixin`) y una Tabla de Logs (`blockchain.registry.entry`).
- **Consumidor (Otros módulos)**: Heredan del Mixin y definen _cómo_ se calcula el Hash de sus documentos.

El flujo de datos es:

1.  **Modelo de Negocio** (ej. `res.partner`) -> 2. **Mixin** (Calcula Hash) -> 3. **Queue** (Tabla `entry`, estado `pending`) -> 4. **Cron Job** (Firma y envía) -> 5. **Blockchain**.
    _(El camino inverso ocurre para confirmación y feedbak en chatter)_

---

## 🛠️ 2. Guía de Integración para Desarrolladores

Esta es la sección más importante. Si estás creando un módulo (ej. `odoo_academy_diplomas`) y quieres que tus diplomas se certifiquen en blockchain, **sigue estos pasos exactos**.

### Paso 1: Añadir Dependencia

En tu `__manifest__.py`, añade `odoo_blockchain_core` como dependencia.

```python
'depends': ['base', 'odoo_blockchain_core'],
```

### Paso 2: Heredar del Mixin Universal

En tu modelo (ej. `academy.diploma`), hereda de `blockchain.certified.mixin`.

```python
from odoo import models, fields, api
import hashlib
import json

class AcademyDiploma(models.Model):
    _name = 'academy.diploma'
    _inherit = ['blockchain.certified.mixin'] # <--- VITAL

    student_name = fields.Char()
    score = fields.Float()
```

### Paso 3: Implementar `_compute_blockchain_hash` (OBLIGATORIO)

El Mixin no sabe qué datos de tu modelo son importantes. Debes decirle qué certificar implementando este método.

**Reglas de Oro:**

1.  **Determinismo**: El mismo documento debe generar SIEMPRE el mismo hash.
2.  **Orden de claves**: Si usas JSON, asegúrate de ordenar las claves (`sort_keys=True`).
3.  **Inmutabilidad**: Si el documento cambia después de certificarlo, el hash cambiará y la verificación fallará.

```python
    def _compute_blockchain_hash(self):
        self.ensure_one()
        # 1. Selecciona los datos críticos que garantizan la autenticidad
        payload = {
            'organization': 'Odoo University',
            'student_name': self.student_name,
            'score': self.score,
            'date': str(self.date_field), # Formatea fechas consistentemente
            'serial_number': self.name
        }

        # 2. Serializa a JSON Bytes de forma consistente
        json_bytes = json.dumps(payload, sort_keys=True).encode('utf-8')

        # 3. Retorna el Hex Digest del SHA-256
        return hashlib.sha256(json_bytes).hexdigest()
```

### Paso 4: Disparar el Registro

Tienes dos opciones para iniciar el proceso:

**Opción A: Automática**
Sobrescribe el método que valida tu documento.

```python
    def action_validate(self):
        self.write({'state': 'done'})
        # Dispara el registro automático
        self.action_blockchain_register()
```

**Opción B: Manual (Botón)**
Añade un botón en tu vista XML. El mixin provee el campo `blockchain_status` que puedes usar para ocultar el botón.

```xml
<button name="action_blockchain_register"
        string="Certificar en Blockchain"
        type="object"
        invisible="blockchain_status != 'draft'"/>
```

### Paso 5: Vistas (Opcional)

Puedes añadir los campos del mixin a tu vista para feedback visual:

```xml
<group string="Blockchain Info">
    <field name="blockchain_status" widget="badge"
           decoration-info="blockchain_status == 'pending'"
           decoration-success="blockchain_status == 'confirmed'"/>
    <field name="blockchain_hash" groups="base.group_no_one"/>
    <field name="blockchain_entry_id" readonly="1"/>
</group>
```

---

## ⚙️ 3. Funcionamiento Interno

![Diagrama de Flujo Completo](docs/Diagrama%20de%20flujo.png)

Una vez que llamas a `action_blockchain_register()`, el módulo toma el control:

1.  **Deduplicación**: Verifica si ese hash ya existe en `blockchain.registry.entry`. Si existe, simplemente enlaza tu registro al entry existente (evita doble gasto de Gas).
2.  **Encolado (Pending)**: Crea un registro en estado `pending`. **No se envía a la blockchain todavía.**
3.  **Cron de Procesamiento (Process Submission Queue)**:
    - Se ejecuta automáticamente (por defecto cada 2-5 min).
    - Verifica si el **Gas Price** de la red es menor a tu configuración límite (`Max Gas Price`).
    - Si es barato, firma la transacción con la **Llave Privada** y la envía (`Submitted`).
    - Si es caro, espera al siguiente ciclo.
4.  **Confirmación**:
    - Otro Cron verifica los recibos de transacción.
    - Cuando se confirma en la blockchain, el estado pasa a `confirmed`.

---

## 🔐 4. Configuración Segura (SysAdmin)

Para que el sistema funcione, necesitas configurar el acceso a la red y la identidad (Wallet).

### Variable de Entorno (CRÍTICO)

La llave privada **NUNCA** se guarda en la base de datos. Se inyecta al iniciar el proceso Odoo.

**Linux / Docker:**

```bash
export ODOO_BLOCKCHAIN_PRIVATE_KEY="0x123456789abcdef..."
./odoo-bin -c odoo.conf
```

**Windows (PowerShell):**

```powershell
$env:ODOO_BLOCKCHAIN_PRIVATE_KEY="0x123456789abcdef..."
python odoo-bin -c odoo.conf
```

### Ajustes en Odoo

Ve a **Ajustes > Blockchain Core**:

1.  **RPC URL**: Endpoint del nodo (Infura, Alchemy, Localhost).
2.  **Chain ID**: ID de la red (1=Mainnet, 11155111=Sepolia).
3.  **Contract Address**: Dirección del Smart Contract desplegado (`UniversalDocumentRegistry`).
4.  **Max Gas Price**: Límite de Gwei dispuesto a pagar.

---

## 🕵️ 5. Verificador Público Universal

El módulo incluye una **Página Web Pública** para que cualquier tercero pueda verificar la autenticidad de un documento sin necesidad de acceder al backend de Odoo.

- **URL**: `/blockchain/verify` (ej. `https://tu-odoo.com/blockchain/verify`)
- **Tecnología**: Web3 / Ethers.js (Ejecutado en el navegador del cliente).

### 🔒 Privacidad y Seguridad (Client-Side Hashing)

Esta herramienta ha sido diseñada con la privacidad en mente:

1.  **Zero-Upload**: El documento original **NUNCA se sube al servidor**.
2.  **Cálculo Local**: El Hash SHA-256 se calcula en el navegador del usuario utilizando la API `crypto.subtle` de HTML5.
3.  **Verificación Directa**: La consulta de validez se hace **directamente desde el navegador del usuario a la Blockchain**, sin pasar por Odoo. Esto garantiza una verificación "Trustless" (sin confianza necesaria en el servidor central).
