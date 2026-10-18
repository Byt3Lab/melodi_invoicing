# MELODI Invoicing — Directives du Module Facturation (`modules/melodi_invoicing/`)

Le module `melodi_invoicing` gère la création de devis, la facturation client et fournisseur, l'échéancier de paiement, l'impression PDF et le suivi des règlements.

---

## 1. Modèles et Schéma de Données

- **`InvoiceModel`** (`ml_inv_invoices`) : Document de facturation (`invoice_id`, `number`, `type`: `'out_invoice'` / `'in_invoice'`, `partner_id`, `date`, `due_date`, `total_untaxed`, `total_tax`, `total_amount`, `status`: `'draft'` / `'posted'` / `'paid'` / `'cancelled'`).
- **`InvoiceLineModel`** (`ml_inv_lines`) : Lignes de factures (`line_id`, `invoice_id`, `product_id`, `description`, `quantity`, `unit_price`, `subtotal`).
- **`InvoicePaymentModel`** (`ml_inv_payments`) : Règlements associés à la facture.

---

## 2. Directives Métier & Événements

1. **Numérotation Séquentielle Inaltérable** :
   Lorsqu'une facture passe de l'état `'draft'` à `'posted'`, un numéro séquentiel unique inaltérable est attribué selon le chronogramme fiscal configuré.
2. **Génération PDF & Barcode** :
   L'impression des factures s'appuie sur la génération HTML/PDF (via `reportlab` ou `pypdf`/`xhtml2pdf`).
3. **Notification d'Événements** :
   - Validation d'une facture (`invoice_posted`) : Émet un événement reçu par `melodi_accounting` pour générer automatiquement l'écriture au journal des ventes/achats.
   - Règlement complet (`invoice_paid`) : Met à jour le statut et envoie les notifications correspondantes.
