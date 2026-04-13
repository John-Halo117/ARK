use crate::types::LKS;

pub fn decide(lks:&LKS)->&'static str{
    if lks.dss>1.5 {"emergency"}
    else if lks.dss>1.0 {"throttle"}
    else {"allow"}
}
