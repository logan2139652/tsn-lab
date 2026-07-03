/*
 * TCQF v1: Tagged Cyclic Queuing and Forwarding
 */

#ifndef __TSN_QUEUE__
#define __TSN_QUEUE__

#include "headers.p4"
#include "defines.p4"

control tsn_queue_control(inout headers_t hdr,
                          inout local_metadata_t local_metadata,
                          inout standard_metadata_t standard_metadata) {

    action set_out_cycle(bit<8> out_cycle) {
        local_metadata.out_cycle = out_cycle;
        hdr.tsn.cycle_tag = out_cycle;
    }

    table tcqf_cycle_map {
        key = {
            standard_metadata.ingress_port : exact;
            hdr.tsn.fid                    : exact;
            hdr.tsn.cycle_tag              : exact;
        }
        actions = {
            set_out_cycle;
            NoAction;
        }
        size = 1024;
        default_action = NoAction();
    }

    action cycle_to_queue() {
        if (hdr.tsn.kind == 8w0) {
            // BE/BG: always queue 0, cycle 7
            hdr.tsn.cycle_tag = 8w7;
            standard_metadata.priority = 3w7;
        } else if (hdr.tsn.cycle_tag == 8w0 || hdr.tsn.cycle_tag == 8w3 || hdr.tsn.cycle_tag == 8w6) {
            standard_metadata.priority = 3w6;
        } else if (hdr.tsn.cycle_tag == 8w1 || hdr.tsn.cycle_tag == 8w4) {
            standard_metadata.priority = 3w5;
        } else if (hdr.tsn.cycle_tag == 8w2 || hdr.tsn.cycle_tag == 8w5) {
            standard_metadata.priority = 3w4;
        } else {
            // cycle 7 (BE only)
            standard_metadata.priority = 3w7;
        }
    }

    apply {
        if (hdr.tsn.isValid()) {
            tcqf_cycle_map.apply();
            cycle_to_queue();
        } else {
            standard_metadata.priority = 3w7;
        }
    }
}

control tsn_debug_egress_control(inout headers_t hdr,
                                 inout local_metadata_t local_metadata,
                                 inout standard_metadata_t standard_metadata) {
    apply {
        if (hdr.tsn.isValid()) {
            hdr.tsn.flags = local_metadata.cycle_tag;
        }
    }
}

#endif
