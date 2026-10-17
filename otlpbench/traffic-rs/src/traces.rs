use super::*;
pub use opentelemetry_proto::tonic::collector::trace::v1::{
    trace_service_server::{TraceService, TraceServiceServer},
    ExportTraceServiceRequest, ExportTraceServiceResponse,
};
use opentelemetry_proto::tonic::common::v1::{any_value, KeyValue};

#[derive(Default, Clone, Serialize)]
pub struct Checks {
    pub roots: u64,
    pub children: u64,
    pub root_ids: u64,
    pub child_ids: u64,
    pub error_trace_spans: u64,
    pub masked: u64,
    pub private: u64,
    pub invalid: u64,
}
impl Checks {
    pub fn merge(&mut self, c: &Self) {
        self.roots += c.roots;
        self.children += c.children;
        self.root_ids = self.root_ids.wrapping_add(c.root_ids);
        self.child_ids = self.child_ids.wrapping_add(c.child_ids);
        self.error_trace_spans += c.error_trace_spans;
        self.masked += c.masked;
        self.private += c.private;
        self.invalid += c.invalid;
    }
}
fn attr<'a>(attrs: &'a [KeyValue], key: &str) -> Option<&'a str> {
    attrs.iter().find(|a| a.key == key).and_then(|a| a.value.as_ref()).and_then(|v| match &v.value {
        Some(any_value::Value::StringValue(v)) => Some(v.as_str()), _ => None,
    })
}
pub fn count(req: &ExportTraceServiceRequest) -> Counts {
    let mut c = Counts { requests: 1, ..Default::default() };
    for r in &req.resource_spans {
        for scope in &r.scope_spans {
            for s in &scope.spans {
                c.points += 1;
                c.value_sum += 1.0;
                if s.trace_id.len() != 16 || s.span_id.len() != 8 { c.trace_checks.invalid += 1; continue; }
                let local = u64::from_be_bytes(s.trace_id[8..].try_into().unwrap());
                let id = u64::from_be_bytes(s.span_id[..].try_into().unwrap());
                let hash = s.trace_id.iter().fold(14695981039346656037u64, |h,b| (h ^ *b as u64).wrapping_mul(1099511628211));
                let error_trace = local % 4 == 0;
                let root = id == 1;
                if root { c.trace_checks.roots += 1; c.trace_checks.root_ids = c.trace_checks.root_ids.wrapping_add(hash); }
                else { c.trace_checks.children += 1; c.trace_checks.child_ids = c.trace_checks.child_ids.wrapping_add(hash); }
                if error_trace { c.trace_checks.error_trace_spans += 1; }
                if attr(&s.attributes,"route") == Some("health") { c.health_points += 1; }
                if attr(&s.attributes,"secret") == Some("REDACTED") { c.trace_checks.masked += 1; }
                if attr(&s.attributes,"secret") == Some("private@example.test") { c.trace_checks.private += 1; }
                let parent_ok = if root { s.parent_span_id.is_empty() || s.parent_span_id.iter().all(|b| *b == 0) } else { s.parent_span_id == 1u64.to_be_bytes() };
                let status = if error_trace && !root { 2 } else { 1 };
                let valid = local > 0 && (id == 1 || id == 2) && parent_ok
                    && s.name == if root { "bench.root" } else { "bench.child" }
                    && s.kind == 2 && s.end_time_unix_nano.checked_sub(s.start_time_unix_nano) == Some(20_000_000)
                    && s.status.as_ref().map(|s| s.code) == Some(status)
                    && attr(&s.attributes,"route") == Some(if error_trace {"health"} else {"api"})
                    && s.events.len() == 1 && s.events[0].name == "checkpoint"
                    && s.links.len() == 1 && s.links[0].trace_id == vec![0x12;16] && s.links[0].span_id == vec![0x13;8];
                if !valid { c.trace_checks.invalid += 1; }
            }
        }
    }
    c
}
pub fn patch(template: &[u8], offset: usize, ids: &[usize], seq: u64) -> Bytes {
    let mut b = BytesMut::from(super::patch_request(template, offset, seq).as_ref());
    // An odd multiplier permutes sequence IDs without collisions.
    let prefix = seq.wrapping_add(1).wrapping_mul(0x9e3779b97f4a7c15).to_be_bytes();
    for &i in ids { b[i..i+8].copy_from_slice(&prefix); }
    b.freeze()
}
#[tonic::async_trait]
impl TraceService for Sink {
    async fn export(&self, req: tonic::Request<ExportTraceServiceRequest>) -> Result<tonic::Response<ExportTraceServiceResponse>, Status> {
        let req = req.into_inner();
        self.accept_counts(count(&req), req.encoded_len()).map_err(Status::internal)?;
        Ok(tonic::Response::new(ExportTraceServiceResponse { partial_success: None }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn trace_ids_are_unique_across_requests_and_preserve_pairs() {
        let template = b"00000000000000000000BENCHID!abcdefghBENCHID!abcdefgh";
        let a = patch(template, 0, &[20,36], 123);
        let b = patch(template, 0, &[20,36], 124);
        assert_eq!(&a[20..36], &a[36..52]);
        assert_ne!(&a[20..36], &b[20..36]);
        assert_eq!(&a[28..36], b"abcdefgh");
        assert_eq!(&a[..20], b"00000000000000000123");
    }
    #[test]
    fn partial_success_responses_share_wire_layout() {
        use opentelemetry_proto::tonic::collector::trace::v1::ExportTracePartialSuccess;
        let trace = ExportTraceServiceResponse {
            partial_success: Some(ExportTracePartialSuccess { rejected_spans: 7, error_message: "rejected".into() }),
        };
        let metrics = ExportMetricsServiceResponse::decode(trace.encode_to_vec().as_slice()).unwrap();
        let partial = metrics.partial_success.unwrap();
        assert_eq!(partial.rejected_data_points, 7);
        assert_eq!(partial.error_message, "rejected");
    }
}
