use lrwn::PhyPayload;
use pyo3::prelude::*;
use pythonize;

#[pymodule]
mod lorawan_decoder {
    #[pymodule_export]
    use super::phy_payload;
}

#[pymodule]
mod phy_payload {
    #[pymodule_export]
    use super::from_bytes;
}

struct PyPhyPayload(PhyPayload);

impl<'py> IntoPyObject<'py> for PyPhyPayload {
    type Target = PyAny;
    type Output = Bound<'py, Self::Target>;
    type Error = pythonize::PythonizeError;

    fn into_pyobject(self, py: Python<'py>) -> Result<Self::Output, Self::Error> {
        pythonize::pythonize(py, &self.0)
    }
}

#[pyfunction]
fn from_bytes(
    b: &[u8],
    plaintext_f_opts: bool,
    plaintext_frm_payload: bool,
) -> PyResult<PyPhyPayload> {
    let mut phy_payload = PhyPayload::from_slice(b)?;
    if plaintext_f_opts {
        if let Err(e) = phy_payload.decode_f_opts_to_mac_commands() {
            println!("Decode f_opts to mac-commands error: {e}");
        }
    }
    if plaintext_frm_payload {
        if let Err(e) = phy_payload.decode_frm_payload() {
            println!("Decode frm_payload error: {e}");
        }
    }
    Ok(PyPhyPayload(phy_payload))
}
