//! Rust code generation: `DeviceModel` -> `firmware/src/generated.rs`.
//!
//! Output is built from `quote!` token streams, parsed into a `syn::File` and
//! formatted by `prettyplease`; no string templates.
//!
//! Conventions of the generated code (the contract for `firmware/src/runtime`):
//! * every component schema names its runtime module in `firmware.module`;
//! * `<module>::Config` is the config struct (nested objects: `<module>::<Prop>Config`,
//!   string enums: `<module>::<Prop>::<Variant>`); optional properties without a default are `Option<_>`;
//! * network components: `<module>::start(spawner, &CONFIG, peripherals..)`;
//! * buses: `<module>::init(&CONFIG, peripherals.., pins..) -> <module>::Bus`, stored in a `StaticCell`;
//! * other components: a generated task calling `<module>::run(&CONFIG, pins.., bus refs..).await`.
//!
//! Argument order is always: config, peripherals, pins (role name order), refs (property name order).

use std::collections::BTreeMap;

use proc_macro2::{Literal, TokenStream};
use quote::{format_ident, quote};
use serde_json::Value;

use crate::error::EngineError;
use crate::model::{ComponentModel, DeviceModel};
use crate::schema::Registry;

fn err(msg: impl Into<String>) -> EngineError {
    EngineError::Codegen(msg.into())
}

/// Generate the formatted Rust source of `generated.rs`.
pub fn generate(model: &DeviceModel, reg: &Registry) -> Result<String, EngineError> {
    let board = reg
        .boards
        .get(&model.board)
        .ok_or_else(|| err(format!("unknown board `{}`", model.board)))?;

    // Network first, then buses, then everything else; stable within a phase.
    let mut ordered: Vec<&ComponentModel> = model.components.iter().collect();
    ordered.sort_by_key(|c| match reg.components.get(&c.component).map(|k| k.kind.as_str()) {
        Some("network") => 0,
        Some("bus") => 1,
        _ => 2,
    });

    let mut items: Vec<TokenStream> = Vec::new();
    let mut setup: Vec<TokenStream> = Vec::new();
    let mut indexed: BTreeMap<String, usize> = BTreeMap::new();
    let mut uses_static_cell = false;
    let mut bus_local: BTreeMap<String, proc_macro2::Ident> = BTreeMap::new(); // yaml id -> local variable

    for cm in ordered {
        let comp = reg
            .components
            .get(&cm.component)
            .ok_or_else(|| err(format!("unknown component `{}`", cm.component)))?;
        let fw = comp
            .firmware
            .as_ref()
            .ok_or_else(|| err(format!("component `{}` has no `firmware` block", comp.id)))?;
        let module: syn::Path =
            syn::parse_str(&fw.module).map_err(|e| err(format!("bad module path `{}`: {e}", fw.module)))?;

        let instance_id = if comp.singleton {
            None
        } else {
            let id = cm
                .config
                .get("id")
                .and_then(Value::as_str)
                .ok_or_else(|| err(format!("{}: missing `id`", cm.path)))?;
            check_ident_part(id, &cm.path)?;
            Some(id)
        };
        let cfg_name = match instance_id {
            Some(id) => format_ident!("CFG_{}", id.to_uppercase()),
            None => format_ident!("{}_CONFIG", comp.id.to_uppercase()),
        };

        // Config static.
        let pin_roles: Vec<&str> = comp.pins.keys().map(String::as_str).collect();
        let refs = comp.refs();
        let skip = |name: &str| {
            name == "platform" || pin_roles.contains(&name) || refs.iter().any(|(p, _)| p == name)
        };
        let fields = struct_fields(&comp.config, Some(&cm.config), &module, &skip, &cm.path)?;
        items.push(quote! {
            static #cfg_name: #module::Config = #module::Config { #(#fields),* };
        });

        // Peripherals, pins.
        let mut periph: Vec<TokenStream> = Vec::new();
        for name in &fw.peripherals {
            let field = ident(name, &cm.path)?;
            periph.push(quote!(p.#field));
        }
        if let Some(prefix) = &fw.indexed_peripheral {
            let n = indexed.entry(prefix.clone()).or_insert(0);
            let field = ident(&format!("{prefix}{n}"), &cm.path)?;
            *n += 1;
            periph.push(quote!(p.#field));
        }
        let mut pins: Vec<(String, TokenStream)> = Vec::new();
        for role in &pin_roles {
            let n = cm
                .config
                .get(*role)
                .and_then(Value::as_u64)
                .ok_or_else(|| err(format!("{}.{role}: pin not set", cm.path)))?;
            let gpio = format_ident!("GPIO{n}");
            pins.push((role.to_string(), quote!(p.#gpio.into())));
        }

        match comp.kind.as_str() {
            "network" => {
                setup.push(quote! { #module::start(spawner, &#cfg_name, #(#periph),*); });
            }
            "bus" => {
                let id = instance_id.ok_or_else(|| err(format!("{}: a bus must not be a singleton", cm.path)))?;
                uses_static_cell = true;
                let bus_static = format_ident!("BUS_{}", id.to_uppercase());
                let local = format_ident!("bus_{}", id);
                let pin_args = pins.iter().map(|(_, t)| t);
                items.push(quote! { static #bus_static: StaticCell<#module::Bus> = StaticCell::new(); });
                setup.push(quote! {
                    let #local = #bus_static.init(#module::init(&#cfg_name, #(#periph,)* #(#pin_args),*));
                });
                bus_local.insert(id.to_owned(), local);
            }
            _ => {
                let id = instance_id.ok_or_else(|| err(format!("{}: unexpected singleton", cm.path)))?;
                let task = format_ident!("task_{}", id);
                if !periph.is_empty() {
                    return Err(err(format!("{}: peripherals on plain components are not supported yet", cm.path)));
                }
                let mut params: Vec<TokenStream> = Vec::new();
                let mut run_args: Vec<TokenStream> = Vec::new();
                let mut call_args: Vec<TokenStream> = Vec::new();
                for (role, call) in &pins {
                    let name = format_ident!("pin_{}", role);
                    params.push(quote!(#name: esp_hal::gpio::AnyPin<'static>));
                    run_args.push(quote!(#name));
                    call_args.push(call.clone());
                }
                for (prop, target) in &refs {
                    let Some(target_id) = cm.config.get(prop).and_then(Value::as_str) else { continue };
                    let target_comp = reg.components.get(target).ok_or_else(|| err(format!("unknown ref target `{target}`")))?;
                    let target_fw = target_comp
                        .firmware
                        .as_ref()
                        .filter(|_| target_comp.kind == "bus")
                        .ok_or_else(|| err(format!("{}.{prop}: only references to buses are supported", cm.path)))?;
                    let target_module: syn::Path = syn::parse_str(&target_fw.module)
                        .map_err(|e| err(format!("bad module path `{}`: {e}", target_fw.module)))?;
                    let local = bus_local
                        .get(target_id)
                        .ok_or_else(|| err(format!("{}.{prop}: bus `{target_id}` was not generated", cm.path)))?;
                    let name = format_ident!("ref_{}", prop);
                    params.push(quote!(#name: &'static #target_module::Bus));
                    run_args.push(quote!(#name));
                    call_args.push(quote!(#local));
                }
                items.push(quote! {
                    #[embassy_executor::task]
                    async fn #task(#(#params),*) {
                        #module::run(&#cfg_name, #(#run_args),*).await
                    }
                });
                setup.push(quote! {
                    if let Ok(token) = #task(#(#call_args),*) {
                        spawner.spawn(token);
                    }
                });
            }
        }
    }

    let header = format!(
        " @generated by builder-engine for board `{}` ({}, target {}). DO NOT EDIT.",
        board.id, board.chip, board.target
    );
    let name = &model.name;
    let board_id = &model.board;
    let static_cell_use = uses_static_cell.then(|| quote!(use static_cell::StaticCell;));
    let tokens = quote! {
        #![doc = #header]

        use embassy_executor::Spawner;
        use esp_hal::peripherals::Peripherals;
        #static_cell_use

        use crate::runtime;

        pub const DEVICE_NAME: &str = #name;
        pub const BOARD: &str = #board_id;

        #(#items)*

        pub async fn setup(spawner: Spawner, p: Peripherals) {
            #(#setup)*
        }
    };
    let file: syn::File = syn::parse2(tokens).map_err(|e| err(format!("generated tokens do not parse: {e}")))?;
    Ok(prettyplease::unparse(&file))
}

/// `field: value` pairs for a config struct literal, in schema-property (alphabetical) order.
fn struct_fields(
    schema: &Value,
    value: Option<&Value>,
    module: &syn::Path,
    skip: &dyn Fn(&str) -> bool,
    path: &str,
) -> Result<Vec<TokenStream>, EngineError> {
    let required: Vec<&str> = schema
        .get("required")
        .and_then(Value::as_array)
        .map(|a| a.iter().filter_map(Value::as_str).collect())
        .unwrap_or_default();
    let mut out = Vec::new();
    let Some(props) = schema.get("properties").and_then(Value::as_object) else {
        return Ok(out);
    };
    for (name, def) in props {
        if skip(name) {
            continue;
        }
        let field = ident(name, path)?;
        let default = def.get("default");
        let always = required.contains(&name.as_str()) || default.is_some();
        let expr = match value.and_then(|v| v.get(name)).or(default) {
            Some(v) => {
                let t = value_tokens(def, v, name, module, &format!("{path}.{name}"))?;
                if always { t } else { quote!(Some(#t)) }
            }
            None if always => return Err(err(format!("{path}.{name}: required value missing"))),
            None => quote!(None),
        };
        out.push(quote!(#field: #expr));
    }
    Ok(out)
}

fn value_tokens(def: &Value, v: &Value, prop: &str, module: &syn::Path, path: &str) -> Result<TokenStream, EngineError> {
    Ok(match v {
        Value::Bool(b) => quote!(#b),
        Value::Number(n) => {
            let lit = if let Some(i) = n.as_i64() {
                Literal::i64_unsuffixed(i)
            } else if let Some(u) = n.as_u64() {
                Literal::u64_unsuffixed(u)
            } else {
                Literal::f64_unsuffixed(n.as_f64().ok_or_else(|| err(format!("{path}: bad number")))?)
            };
            quote!(#lit)
        }
        Value::String(s) if def.get("enum").is_some() => {
            let ty = ident(&pascal(prop), path)?;
            let variant = ident(&pascal(s), path)?;
            quote!(#module::#ty::#variant)
        }
        Value::String(s) => quote!(#s),
        Value::Object(_) => {
            let ty = ident(&format!("{}Config", pascal(prop)), path)?;
            let fields = struct_fields(def, Some(v), module, &|_| false, path)?;
            quote!(#module::#ty { #(#fields),* })
        }
        Value::Array(items) => {
            let item_def = def.get("items").unwrap_or(&Value::Null);
            let elems = items
                .iter()
                .enumerate()
                .map(|(i, e)| value_tokens(item_def, e, prop, module, &format!("{path}[{i}]")))
                .collect::<Result<Vec<_>, _>>()?;
            quote!(&[#(#elems),*])
        }
        Value::Null => return Err(err(format!("{path}: null is not supported"))),
    })
}

/// `always_off` -> `AlwaysOff`.
fn pascal(s: &str) -> String {
    s.split('_')
        .filter(|w| !w.is_empty())
        .map(|w| {
            let mut c = w.chars();
            c.next().map(|f| f.to_ascii_uppercase().to_string() + c.as_str()).unwrap_or_default()
        })
        .collect()
}

fn ident(s: &str, path: &str) -> Result<proc_macro2::Ident, EngineError> {
    syn::parse_str::<syn::Ident>(s).map_err(|_| err(format!("{path}: `{s}` is not a valid Rust identifier")))
}

/// Ids are spliced into identifiers behind a prefix, so only `[A-Za-z0-9_]` is needed.
fn check_ident_part(s: &str, path: &str) -> Result<(), EngineError> {
    if !s.is_empty() && s.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') {
        Ok(())
    } else {
        Err(err(format!("{path}: id `{s}` cannot be used in a Rust identifier")))
    }
}
