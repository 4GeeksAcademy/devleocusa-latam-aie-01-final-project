"""Seed script for initial logistics carriers and demo CRM leads in TinyDB."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from src.database import db, get_suppliers_table
from src.models.lead import LeadResponse, LeadStatus
from src.models.supplier import (
    SupplierCategory,
    SupplierCountry,
    SupplierResponse,
    SupplierStatus,
)


def build_seed_suppliers() -> list[SupplierResponse]:
    """Build the initial suppliers payload using validated Pydantic models."""

    seed_rows = [
        ("UPS", SupplierCountry.ESTADOS_UNIDOS),
        ("FedEx", SupplierCountry.ESTADOS_UNIDOS),
        ("DHL", SupplierCountry.ESTADOS_UNIDOS),
        ("MRW", SupplierCountry.ESPANA),
        ("SEUR", SupplierCountry.ESPANA),
        ("DHL", SupplierCountry.ESPANA),
    ]

    now = datetime.now(timezone.utc)
    suppliers: list[SupplierResponse] = []

    for nombre, pais in seed_rows:
        suppliers.append(
            SupplierResponse(
                id=str(uuid4()),
                nombre=nombre,
                pais=pais,
                categorias=[SupplierCategory.ULTIMA_MILLA],
                tarifa=10.0,
                estado=SupplierStatus.ACTIVO,
                updated_at=now,
            )
        )

    return suppliers


def build_seed_leads() -> list[LeadResponse]:
    """Build realistic demo leads using validated Pydantic models."""

    now = datetime.now(timezone.utc)
    seed_rows = [
        {
            "company_name": "Luna Cosmetics",
            "contact_person": "Carmen Ruiz",
            "corporate_email": "carmen.ruiz@lunacosmetics.es",
            "phone": "+34 612 334 455",
            "website": "https://www.lunacosmetics.es",
            "country_operation": "España",
            "product_type": "Cosmética",
            "monthly_volume": "501-2000",
            "services": ["Almacenaje", "Última milla"],
            "other_3pl": "No",
            "comments": "Buscan un almacén en Madrid con entregas el mismo día.",
            "privacy_policy": True,
            "status": LeadStatus.NEW,
            "created_at_offset_days": 0,
        },
        {
            "company_name": "Moda Viva",
            "contact_person": "Alejandro Paredes",
            "corporate_email": "a.paredes@modaviva.com",
            "phone": "+52 55 8899 0011",
            "website": "https://www.modaviva.com",
            "country_operation": "Ambos",
            "product_type": "Moda",
            "monthly_volume": "2000+",
            "services": ["Almacenaje", "Última milla", "Logística inversa"],
            "other_3pl": "Estoy evaluando opciones",
            "comments": "Requieren devoluciones gestionadas y visibilidad de inventario compartida.",
            "privacy_policy": True,
            "status": LeadStatus.CONTACTED,
            "created_at_offset_days": 1,
        },
        {
            "company_name": "RapidShip Electronics",
            "contact_person": "Sofía Navarro",
            "corporate_email": "sofia.navarro@rapidship.io",
            "phone": "+1 305 771 2290",
            "website": "https://www.rapidship.io",
            "country_operation": "Estados Unidos",
            "product_type": "Electrónica",
            "monthly_volume": "101-500",
            "services": ["Última milla"],
            "other_3pl": "Sí",
            "comments": "",
            "privacy_policy": True,
            "status": LeadStatus.QUALIFIED,
            "created_at_offset_days": 2,
        },
        {
            "company_name": "Green Gourmet",
            "contact_person": "Lucía Hernández",
            "corporate_email": "lucia@greengourmet.fr",
            "phone": "+33 6 45 21 87 90",
            "website": None,
            "country_operation": "Ambos",
            "product_type": "Alimentación",
            "monthly_volume": "101-500",
            "services": ["Almacenaje"],
            "other_3pl": "No",
            "comments": "Productos refrigerados, requiere control de temperatura en tránsito.",
            "privacy_policy": True,
            "status": LeadStatus.NEW,
            "created_at_offset_days": 3,
        },
        {
            "company_name": "Atelier Norte",
            "contact_person": "María Gutiérrez",
            "corporate_email": "m.gutierrez@ateliernorte.com",
            "phone": "+34 610 882 340",
            "website": "https://www.ateliernorte.com",
            "country_operation": "España",
            "product_type": "Moda",
            "monthly_volume": "0-100",
            "services": ["Logística inversa"],
            "other_3pl": "Estoy evaluando opciones",
            "comments": "Proyecto piloto para devoluciones de temporada.",
            "privacy_policy": True,
            "status": LeadStatus.DISQUALIFIED,
            "created_at_offset_days": 5,
        },
    ]

    leads: list[LeadResponse] = []
    for row in seed_rows:
        status = row.pop("status")
        offset_days = row.pop("created_at_offset_days")
        created_at = now - timedelta(days=offset_days)
        leads.append(
            LeadResponse(
                id=str(uuid4()),
                status=status,
                created_at=created_at,
                updated_at=created_at,
                **row,
            )
        )

    return leads


def main() -> int:
    suppliers_table = get_suppliers_table()

    if len(suppliers_table) > 0:
        print("La base de datos ya contiene registros. No se insertaron datos duplicados.")
        return 0

    suppliers = build_seed_suppliers()
    payload = [supplier.model_dump(mode="json") for supplier in suppliers]
    inserted_ids = suppliers_table.insert_multiple(payload)

    print(f"Registros insertados: {len(inserted_ids)}")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
