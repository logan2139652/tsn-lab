/*
 * Copyright 2017-present Open Networking Foundation
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#ifndef __TSN_QUEUE__
#define __TSN_QUEUE__

#include "headers.p4"
#include "defines.p4"

control tsn_queue_control(inout headers_t hdr,
                          inout local_metadata_t local_metadata,
                          inout standard_metadata_t standard_metadata) {

    action compute_arrival_slot() {
        bit<48> ts;
        ts = standard_metadata.ingress_global_timestamp;

        /* TQF-pow2-slot:
         * slot_us = 8192 = 2^13, slots_per_cycle = 8.
         * arrival_slot = floor(timestamp / 8192) mod 8 = ts[15:13].
         */
        local_metadata.arrival_slot = (bit<8>) ts[15:13];
    }

    action assign_out_slot_d1() {
        if (local_metadata.arrival_slot == 8w0) {
            local_metadata.out_slot = 8w1;
        } else if (local_metadata.arrival_slot == 8w1) {
            local_metadata.out_slot = 8w2;
        } else if (local_metadata.arrival_slot == 8w2) {
            local_metadata.out_slot = 8w3;
        } else if (local_metadata.arrival_slot == 8w3) {
            local_metadata.out_slot = 8w4;
        } else if (local_metadata.arrival_slot == 8w4) {
            local_metadata.out_slot = 8w5;
        } else if (local_metadata.arrival_slot == 8w5) {
            local_metadata.out_slot = 8w6;
        } else if (local_metadata.arrival_slot == 8w6) {
            local_metadata.out_slot = 8w7;
        } else {
            /* Queue 0 is reserved for BE fallback. A packet that would wrap
             * from slot 7 to slot 0 is deferred to the next TSN slot instead.
             */
            local_metadata.out_slot = 8w1;
        }

        hdr.tsn.cycle_tag = local_metadata.out_slot;
        hdr.tsn.flags = local_metadata.arrival_slot;
    }

    action assign_out_slot_d2() {
        if (local_metadata.arrival_slot == 8w0) {
            local_metadata.out_slot = 8w2;
        } else if (local_metadata.arrival_slot == 8w1) {
            local_metadata.out_slot = 8w3;
        } else if (local_metadata.arrival_slot == 8w2) {
            local_metadata.out_slot = 8w4;
        } else if (local_metadata.arrival_slot == 8w3) {
            local_metadata.out_slot = 8w5;
        } else if (local_metadata.arrival_slot == 8w4) {
            local_metadata.out_slot = 8w6;
        } else if (local_metadata.arrival_slot == 8w5) {
            local_metadata.out_slot = 8w7;
        } else if (local_metadata.arrival_slot == 8w6) {
            local_metadata.out_slot = 8w0;
        } else {
            local_metadata.out_slot = 8w1;
        }

        hdr.tsn.cycle_tag = local_metadata.out_slot;
        hdr.tsn.flags = local_metadata.arrival_slot;
    }

    action set_base_queue_from_out_slot() {
        if (local_metadata.out_slot == 8w0) {
            local_metadata.base_queue = 8w0;
        } else if (local_metadata.out_slot == 8w1) {
            local_metadata.base_queue = 8w1;
        } else if (local_metadata.out_slot == 8w2) {
            local_metadata.base_queue = 8w2;
        } else if (local_metadata.out_slot == 8w3) {
            local_metadata.base_queue = 8w3;
        } else if (local_metadata.out_slot == 8w4) {
            local_metadata.base_queue = 8w4;
        } else if (local_metadata.out_slot == 8w5) {
            local_metadata.base_queue = 8w5;
        } else if (local_metadata.out_slot == 8w6) {
            local_metadata.base_queue = 8w6;
        } else {
            local_metadata.base_queue = 8w7;
        }
    }

    action set_be_queue() {
        local_metadata.arrival_slot = 8w0;
        local_metadata.out_slot = 8w0;
        local_metadata.base_queue = 8w0;
        hdr.tsn.cycle_tag = 8w0;
        hdr.tsn.flags = 8w0;
    }

    action set_priority_from_queue() {
        if (local_metadata.base_queue == 8w0) {
            standard_metadata.priority = 3w7;
        } else if (local_metadata.base_queue == 8w1) {
            standard_metadata.priority = 3w6;
        } else if (local_metadata.base_queue == 8w2) {
            standard_metadata.priority = 3w5;
        } else if (local_metadata.base_queue == 8w3) {
            standard_metadata.priority = 3w4;
        } else if (local_metadata.base_queue == 8w4) {
            standard_metadata.priority = 3w3;
        } else if (local_metadata.base_queue == 8w5) {
            standard_metadata.priority = 3w2;
        } else if (local_metadata.base_queue == 8w6) {
            standard_metadata.priority = 3w1;
        } else {
            standard_metadata.priority = 3w0;
        }
    }

    action set_cbqf_batch_queue() {
        local_metadata.arrival_slot = 8w0;
        local_metadata.out_slot = 8w0;

        if ((hdr.tsn.cycle_tag & 8w1) == 8w0) {
            local_metadata.base_queue = 8w1;
        } else {
            local_metadata.base_queue = 8w2;
        }

        /* For CBQF debugging, flags records the selected batch queue. */
        hdr.tsn.flags = local_metadata.base_queue;
    }

    apply {
        if (hdr.tsn.isValid() && hdr.tsn.kind == 8w1) {
            set_cbqf_batch_queue();
            set_priority_from_queue();
        } else {
            if (hdr.tsn.isValid()) {
                set_be_queue();
            }
            standard_metadata.priority = 3w7;
        }
    }
}

control tsn_debug_egress_control(inout headers_t hdr,
                                 inout local_metadata_t local_metadata,
                                 inout standard_metadata_t standard_metadata) {
    apply {
        if (hdr.tsn.isValid()) {
            hdr.tsn.flags = local_metadata.base_queue;
        }
    }
}

#endif
