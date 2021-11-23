import shutil

from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

import click
import pydantic

from pyinvoice.models import Company, Customer, Invoice, Series
from pyinvoice.utils import write_json


DEFAULT_CONFIG_NAME = ".pyinvoice.conf"
DEFAULT_CONFIG_PATH = Path.home() / DEFAULT_CONFIG_NAME


class InvoiceConfigError(Exception):
    pass


class ConfigCompany(pydantic.BaseModel):
    alias: str
    company: Company
    invoices: Optional[List[Invoice]]

    @pydantic.validator("invoices", always=True)
    def none_to_list(cls, v):  # noqa
        return v if v is not None else []

    def get_new_invoice_number_by_series(self, series: Series):
        series_groups = defaultdict(list)
        for invoice in self.invoices or []:
            series_groups[invoice.series].append(invoice)
        series_invoices = series_groups.get(series, None)
        if series_invoices is None:
            return 1
        return max(invoice.number for invoice in series_invoices) + 1

    class Config:
        validate_all = True
        validate_assignment = True


class ConfigCustomer(pydantic.BaseModel):
    alias: str
    customer: Customer

    class Config:
        validate_all = True
        validate_assignment = True


class Config(pydantic.BaseModel):
    companies: List[ConfigCompany]
    customers: List[ConfigCustomer]
    custom_templates_dir: Optional[pydantic.DirectoryPath]

    @pydantic.root_validator(skip_on_failure=True)
    def _validate(cls, values: Dict):  # noqa
        for field in ("companies", "customers"):
            aliases = [obj.alias for obj in values[field]]
            if len(aliases) != len(set(aliases)):
                raise ValueError("Company and Customer aliases must be unique.")
        return values

    def get_company_config_by_alias(self, alias: str):
        for company in self.companies:
            if company.alias == alias:
                return company
        return None

    def get_customer_by_alias(self, alias: str):
        for customer in self.customers:
            if customer.alias == alias:
                return customer.customer
        return None

    class Config:
        validate_all = True
        validate_assignment = True


class ConfigFile:
    def __init__(self, config_path: Optional[str]):
        if config_path is None:
            self.path = DEFAULT_CONFIG_PATH
        else:
            self.path = Path(config_path)
            if self.path.is_dir():
                self.path = self.path / DEFAULT_CONFIG_NAME
        try:
            with open(self.path) as fh:
                raw = fh.read()
                self.config = Config.parse_raw(raw)
                self.backup_raw = raw
        except FileNotFoundError:
            raise InvoiceConfigError(
                f"""
            Config file does not exist at {str(self.path.absolute())}
            You can generate sample config with `invoice sample_config` command."""
            )
        except pydantic.ValidationError as e:
            errors_repr = "\n".join(
                f"{' -> '.join([str(x) for x in error['loc']])}: {error['msg']}"
                for error in e.errors()
            )
            raise InvoiceConfigError(
                f"""
            Something went wrong when parsing {str(self.path)}:
            {errors_repr}"""
            )

    def save(self):
        try:
            write_json(self.config.json(indent=4), self.path)
        except Exception as e:
            # just in case something goes wrong here
            # probably should revisit this later for extra safety
            with open(self.path, "w") as fh:
                fh.write(self.backup_raw)
            raise e


def write_sample_config(path: Optional[str] = None):
    if path is None:
        config_path = DEFAULT_CONFIG_PATH
    else:
        config_path = Path(path)

    if config_path.is_dir():
        config_path = config_path / DEFAULT_CONFIG_NAME

    sample = Path(__file__).parent / "sample_config.json"
    if config_path.exists():
        if click.confirm(
            f"Config file exists at {config_path}, are you sure you want to override it with sample?"
        ) and click.confirm("ARE YOU 100% SURE?"):
            shutil.copy(sample, DEFAULT_CONFIG_PATH)
            return
        click.echo("Aborting")
