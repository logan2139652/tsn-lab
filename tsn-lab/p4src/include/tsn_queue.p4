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
    apply {
        if (local_metadata.is_tsn == 1w1) {
            standard_metadata.priority = local_metadata.qid[2:0];
        } else {
            // map all packets to priority 7, and enter queue 0.
            standard_metadata.priority = 3w7;
        }
    }
}

control tsn_debug_egress_control(inout headers_t hdr,
                                 inout local_metadata_t local_metadata,
                                 inout standard_metadata_t standard_metadata) {
    apply {
        if (hdr.tsn.isValid()) {
            // hdr.tsn.flags = standard_metadata.deq_qdepth[7:0];
            hdr.tsn.flags = local_metadata.qid;
        }
    }
}

#endif
